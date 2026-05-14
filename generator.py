import logging
import os
import random
from collections import Counter

import anthropic
from anthropic.types import TextBlock

from config import BotConfig
from storage import GeneratedPost, Session, log_generated_post

log = logging.getLogger(__name__)

GENERATION_MODEL = "claude-haiku-4-5-20251001"  # TODO - config?
MAX_POST_LENGTH = 280

_SYSTEM_SUFFIX = (
    "\n\nRULES:\n"
    "- Reply with ONLY the post text. No quotes, no preamble, no explanation.\n"
    f"- Hard maximum: {MAX_POST_LENGTH} characters.\n"
    "- Write in first person as the described persona.\n"
    "- Never break character or add meta-commentary."
)

# Mock templates by bot_id - just testing
_MOCK_TEMPLATES: dict[str, list[str]] = {
    "1A": [
        "We cannot afford to stay silent on {topic}. The time for action is now. #ActNow #Justice",
        "Every single person deserves dignity. What's happening with {topic} is unacceptable. #HumanRights",
        "The establishment keeps ignoring {topic}. We keep showing up anyway. #Resistance",
        "Thread on why {topic} matters more than the media lets on: it's about power. #Politics",
    ],
    "1B": [
        "Still thinking about {topic}. A lot to process.",
        "The conversation around {topic} shifted again this week.",
        "Hard to look away from what's happening with {topic} right now.",
        "Not enough people are talking about {topic}.",
    ],
    "2A": [
        "Spent the morning looking at {topic} - the engineering tradeoffs here are genuinely interesting.",
        "Hot take on {topic}: the hype is real but so are the limitations. Here's why.",
        "The latest developments in {topic} are moving faster than most people realise.",
        "{topic} is quietly becoming one of the most important problems in the field.",
    ],
    "2B": [
        "ok {topic} just broke my brain a little ngl",
        "nobody is ready for what {topic} is about to do to the industry",
        "{topic}?? in THIS economy?? let's go",
        "just caught up on {topic} and i have questions. so many questions.",
    ],
}

_MOCK_TEMPLATES_DEFAULT = [
    "Interesting developments in {topic} today.",
    "Been following {topic} closely - worth paying attention to.",
    "Quick thoughts on {topic}: more nuance needed in this conversation.",
]


class PostGenerator:
    """
    Generates posts.
    One instance per bot; create in main.py and pass to Bot.

    Prompt caching: the system prompt (persona + rules) is marked ephemeral.

    if mock=True skip the API entirely and fills in a template instead.
    """

    def __init__(self, bot: BotConfig, mock: bool = False, api_key: str | None = None):
        self.bot = bot
        self.mock = mock
        if not mock:
            self._client = anthropic.Anthropic(
                api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            )
        self._system_text = bot.persona_prompt + _SYSTEM_SUFFIX

    def generate( self, session: "Session", recent_topics: list[str] | None = None, topic_seed: str | None = None) -> GeneratedPost | None:
        """
        Generate one post for this bot and record it in the DB.

        recent_topics: topic labels from posts seen in the current session.
        topic_seed   : explicit override - skip topic selection.

        Returns a flushed GeneratedPost, or None on failure.
        """
        if not self.bot.persona_prompt:
            return None

        topic = topic_seed or self._pick_topic(recent_topics)

        if self.mock:
            return self._generate_mock(session, topic)
        return self._generate_api(session, topic)

    # ---------------------------------------------------------------------------
    # Private
    # ---------------------------------------------------------------------------

    def _generate_mock(self, session: "Session", topic: str) -> GeneratedPost | None:
        templates = _MOCK_TEMPLATES.get(self.bot.bot_id, _MOCK_TEMPLATES_DEFAULT)
        text = random.choice(templates).format(topic=topic)
        log.info("[%s] [MOCK] Generated post topic='%s': %s", self.bot.bot_id, topic, text)
        return log_generated_post(
            session=session,
            bot_id=self.bot.bot_id,
            text=text,
            topic_seed=topic,
            prompt_tokens=0,
            completion_tokens=0,
        )

    def _generate_api(self, session: "Session", topic: str) -> GeneratedPost | None:
        try:
            system_text = self._system_text.format(topic=topic)
        except (KeyError, ValueError):
            system_text = self._system_text

        try:
            response = self._client.messages.create(
                model=GENERATION_MODEL,
                max_tokens=150,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Write a post about: {topic}",
                    }
                ],
            )

            first = response.content[0]
            if not isinstance(first, TextBlock):
                log.error("[%s] Unexpected response block type: %s", self.bot.bot_id, type(first))
                return None
            text = _enforce_length(first.text.strip())

            log.info(
                "[%s] Generated post (%d chars) topic='%s': %s...",
                self.bot.bot_id, len(text), topic, text[:60],
            )

            return log_generated_post(
                session=session,
                bot_id=self.bot.bot_id,
                text=text,
                topic_seed=topic,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
            )

        except anthropic.APIError as e:
            log.error("[%s] Anthropic API error during generation: %s", self.bot.bot_id, e)
            return None
        except Exception as e:
            log.error("[%s] Post generation failed: %s", self.bot.bot_id, e)
            return None

    def _pick_topic(self, recent_topics: list[str] | None) -> str:
        """Feed-driven topic selection, falls back to a random interest topic."""
        if recent_topics:
            counts = Counter(t for t in recent_topics if t != "other")
            if counts:
                return max(counts, key=lambda t: counts[t])
        return random.choice(self.bot.interest_topics)


def _enforce_length(text: str) -> str:
    """Truncate at a word boundary to fit MAX_POST_LENGTH."""
    if len(text) <= MAX_POST_LENGTH:
        return text
    truncated = text[:MAX_POST_LENGTH]
    last_space = truncated.rfind(" ")
    if last_space > MAX_POST_LENGTH - 40:
        return truncated[:last_space].rstrip()
    return truncated
