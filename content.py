import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING
from langdetect import detect

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer, util as st_util

log = logging.getLogger(__name__)

#  ---------------------------------------------------------------------------
#  Optional imports - degrade gracefully if not installed
#  ---------------------------------------------------------------------------

try:
    from sentence_transformers import SentenceTransformer, util as st_util
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    log.warning(
        "sentence-transformers not installed. "
        "Cosine scoring will use keyword fallback."
    )


#  ---------------------------------------------------------------------------
#  Model config
#  ---------------------------------------------------------------------------

EMBEDDING_MODEL = "all-MiniLM-L6-v2"

#  Engagement normalisation cap - likes/reposts above this are treated as max
MAX_LIKES_CAP = 500
MAX_REPOSTS_CAP = 200


#  ---------------------------------------------------------------------------
#  Result dataclass
#  ---------------------------------------------------------------------------

@dataclass
class ScoringResult:
    """
    Full scoring breakdown for a single post against a single bot.
    Stored in the database alongside the seen post for later analysis.
    """
    cosine_score: float         #  0.0 - 1.0, similarity to interest vector
    engagement_score: float     #  0.0 - 1.0, normalised engagement
    final_score: float          #  weighted combination of the two
    language: str | None        #  detected language
    passed_language: bool       #  passed the language filter
    passed_threshold: bool      #  final_score >= bot's cosine_threshold
    passed_filter: bool         #  passed_language AND passed_threshold


#  ---------------------------------------------------------------------------
#  ContentScorer
#  ---------------------------------------------------------------------------

class ContentScorer:
    """
    Shared scoring engine.

    Usage:
        scorer = ContentScorer()
        scorer.load_model()

        #  At startup, embed each bot's interest vector:
        vec = scorer.embed_interests(["climate policy", "human rights"])

        #  During a session, score each post:
        result = scorer.score(
            post_text="New climate bill passed today",
            interest_embedding=vec,
            like_count=42,
            repost_count=8,
            cosine_threshold=0.75,
            engagement_weight=0.2,
            language_filter="en",   #  None = no filter
        )
    """

    def __init__(self):
        self._model: "SentenceTransformer | None" = None
        self._model_loaded = False

    def load_model(self) -> None:
        """
        Load the embedding model.
        """
        if not _ST_AVAILABLE:
            log.warning("sentence-transformers unavailable - using keyword fallback scorer")
            self._model_loaded = False
            return

        log.info("Loading embedding model: %s", EMBEDDING_MODEL)
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Embedding model device: %s", device)
        self._model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        self._model_loaded = True
        log.info("Embedding model loaded")

    def embed_interests(self, topics: list[str]) -> np.ndarray:
        """
        Convert a bot's interest topic list into a single embedding vector.
        Call once per bot at startup and cache the result in the Bot instance.

        If the model is unavailable falls back to a zero vector (keyword
        fallback will handle scoring).
        """
        if not self._model_loaded or self._model is None:
            return np.zeros(384)    #  all-MiniLM-L6-v2 produces 384-dim vectors

        #  Join topics into a single sentence
        interest_text = ". ".join(topics)
        embedding = self._model.encode(interest_text, convert_to_numpy=True)
        log.debug("Embedded interest vector for topics: %s", topics)
        return embedding

    def score(
        self,
        post_text: str,
        interest_embedding: np.ndarray,
        like_count: int,
        repost_count: int,
        cosine_threshold: float,
        engagement_weight: float,
        language_filter: str | None = None,
    ) -> ScoringResult:
        """
        Score a post against a bot's interest vector.

        cosine_threshold : minimum final_score to pass the filter
        engagement_weight: 0.0 = pure cosine, 1.0 = pure engagement
        language_filter  : ISO 639-1 code e.g. "sk", None = no filter
        """
        #  1. Language detection
        detected_lang = self._detect_language(post_text)
        passed_language = (
            language_filter is None
            or detected_lang == language_filter
        )

        #  2. Cosine similarity
        cosine = self._cosine_score(post_text, interest_embedding)

        #  3. Engagement score
        engagement = self._engagement_score(like_count, repost_count)

        #  4. Final score
        #  engagement_weight controls the blend:
        #    0.0 -> purely cosine
        #    1.0 -> purely engagement
        final = (
            (1.0 - engagement_weight) * cosine
            + engagement_weight * engagement
        )

        passed_threshold = final >= cosine_threshold
        passed_filter = passed_language and passed_threshold

        return ScoringResult(
            cosine_score=round(cosine, 4),
            engagement_score=round(engagement, 4),
            final_score=round(final, 4),
            language=detected_lang,
            passed_language=passed_language,
            passed_threshold=passed_threshold,
            passed_filter=passed_filter,
        )

    #  ---------------------------------------------------------------------------
    #  Private helpers
    #  ---------------------------------------------------------------------------

    def _cosine_score( self, post_text: str, interest_embedding: np.ndarray) -> float:
        """
        Compute cosine similarity between a post and a bot's interest vector.
        Falls back to keyword overlap scoring if the model is not loaded.
        """
        if not self._model_loaded or self._model is None:
            return self._keyword_fallback_score(post_text, interest_embedding)

        if not _ST_AVAILABLE:
            return 0.0

        try:
            post_embedding = self._model.encode(post_text, convert_to_numpy=True)
            similarity = float(st_util.cos_sim(interest_embedding, post_embedding))
            return max(0.0, min(1.0, similarity))
        except Exception as e:
            log.warning("Cosine scoring failed: %s - returning 0.0", e)
            return 0.0

    def _engagement_score(self, like_count: int, repost_count: int) -> float:
        """
        Normalise raw engagement counts to a 0.0-1.0 score.
        Uses log scale so viral posts don't dominate.
        """
        if like_count == 0 and repost_count == 0:
            return 0.0

        #  cap then normalise to [0, 1] via log scale
        likes_norm = math.log1p(min(like_count, MAX_LIKES_CAP)) / math.log1p(MAX_LIKES_CAP)
        reposts_norm = math.log1p(min(repost_count, MAX_REPOSTS_CAP)) / math.log1p(MAX_REPOSTS_CAP)

        return round(0.4 * likes_norm + 0.6 * reposts_norm, 4)

    def _detect_language(self, text: str) -> str | None:
        """
        Detect the language of a post.
        Returns None if detection fails.
        """
        if not text or len(text.strip()) < 10:
            return None
        try:
            return detect(text)
        except Exception:
            return None

    def _keyword_fallback_score(
        self,
        _post_text: str,
        interest_embedding: np.ndarray,
    ) -> float:
        """
        Fallback when sentence-transformers is not available.
        Only used during development without the model.

        interest_embedding is a zero vector in fallback mode so this
        always returns 0.5 as a neutral score, meaning all posts pass
        a default threshold and the simulation can still run.
        """
        if np.all(interest_embedding == 0):
            return 0.5
        return 0.0


#  ---------------------------------------------------------------------------
#  Topic extraction helper
#  Used by FeedSnapshot logic in bot.py to cluster posts by topic
#  ---------------------------------------------------------------------------

TOPIC_KEYWORDS: dict[str, list[str]] = {    #  TODO improve this
    "politics":   ["election", "vote", "government", "parliament", "policy",
                   "protest", "rights", "law", "minister", "party"],
    "tech":       ["code", "software", "ai", "model", "open source", "gpu",
                   "developer", "python", "rust", "cybersecurity", "startup"],
    "gaming":     ["game", "rpg", "fps", "patch", "dlc", "indie", "steam",
                   "playstation", "xbox", "nintendo", "esports"],
    "news":       ["breaking", "report", "economy", "trade", "climate",
                   "science", "study", "research", "bank", "inflation"],
    "slovak":     ["slovensko", "vláda", "bratislava", "zákon", "správy",
                   "parlament", "volby", "škola", "zdravie", "región"],
}


def detect_topic(text: str) -> str:
    """
    Assign topic label to a post using keyword matching.
    Used for feed snapshot clustering - not for filtering decisions.
    Returns "other" if no topic matches.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        scores[topic] = sum(1 for kw in keywords if kw in text_lower)
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else "other"