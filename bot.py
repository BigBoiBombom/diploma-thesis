import logging
import random
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session as DbSession, sessionmaker

from bluesky import BaseBlueSkyClient
from config import BotConfig, FEED_FETCH_LIMIT
from content import ContentScorer, detect_topic
from generator import PostGenerator
from storage import SeenPost, log_action, log_seen_post

log = logging.getLogger(__name__)


class Bot:

    def __init__(
        self,
        config: BotConfig,
        db_factory: sessionmaker,
        client: BaseBlueSkyClient,
        scorer: ContentScorer,
        interest_embedding: np.ndarray,
        generator: PostGenerator | None = None,
    ):
        self.config = config
        self.db_factory = db_factory
        self.client = client
        self.scorer = scorer
        self.interest_embedding = interest_embedding
        self.generator = generator
        self._sessions_per_day = max(1, len(config.schedule.session_hours))

    #  ---------------------------------------------------------------------------
    #  Public API
    #  ---------------------------------------------------------------------------

    def run_session(self) -> dict:
        """
        Execute one scheduled session. Returns a summary dict.
        Commits to DB on success; rollback on unhandled exception.
        """
        bot_id = self.config.bot_id
        log.info("[%s] Session starting", bot_id)
        summary = {
            "bot_id": bot_id,
            "seen": 0,
            "likes": 0,
            "reposts": 0,
            "follows": 0,
            "posts": 0,
        }

        db: DbSession = self.db_factory()
        try:
            self._consume_feed(db, summary)
            self._maybe_post(db, summary)
            db.commit()
            log.info("[%s] Session done: %s", bot_id, summary)
        except Exception:
            db.rollback()
            log.exception("[%s] Session failed - rolled back", bot_id)
            raise
        finally:
            db.close()

        return summary

    #  ---------------------------------------------------------------------------
    #  Private - feed consumption
    #  ---------------------------------------------------------------------------

    def _consume_feed(self, db: DbSession, summary: dict) -> None:
        feed_page = self.client.get_timeline(limit=FEED_FETCH_LIMIT)
        posts = feed_page.posts

        seen_uris = self._get_seen_uris(db)
        session_uris: set[str] = set()

        daily_min, daily_max = self.config.consumption.likes_per_day
        session_budget = max(1, round(
            random.randint(daily_min, daily_max) / self._sessions_per_day
        ))
        likes_done = 0

        liked_authors: dict[str, int] = defaultdict(int)
        summary["recent_topics"] = []

        for post in posts:
            if post.uri in seen_uris or post.uri in session_uris:
                continue
            session_uris.add(post.uri)

            result = self.scorer.score(
                post_text=post.text,
                interest_embedding=self.interest_embedding,
                like_count=post.like_count,
                repost_count=post.repost_count,
                cosine_threshold=self.config.consumption.cosine_threshold,
                engagement_weight=self.config.consumption.engagement_weight,
                language_filter=self.config.consumption.language_filter,
            )

            topic = detect_topic(post.text)
            summary["recent_topics"].append(topic)

            #  Log every seen post for analysis
            seen_rec = log_seen_post(
                session=db,
                bot_id=self.config.bot_id,
                uri=post.uri,
                cid=post.cid,
                author_did=post.author_did,
                author_handle=post.author_handle,
                text=post.text,
                post_created_at=post.created_at,
                cosine_score=result.cosine_score,
                engagement_score=result.engagement_score,
                final_score=result.final_score,
                language=result.language,
                passed_filter=result.passed_filter,
                topic=topic,
            )
            summary["seen"] += 1

            #  source_filter: 3B only interacts with verified accounts
            if (self.config.consumption.source_filter == "verified_only"
                    and not post.is_verified):
                continue

            if not result.passed_filter:
                continue

            #  Like
            if likes_done < session_budget:
                ok = self.client.like_post(post.uri, post.cid)
                log_action(
                    session=db,
                    bot_id=self.config.bot_id,
                    action_type="like",
                    target_uri=post.uri,
                    seen_post_id=seen_rec.id,
                    success=ok,
                )
                if ok:
                    likes_done += 1
                    liked_authors[post.author_did] += 1
                    summary["likes"] += 1

            #  Repost
            if (self.config.posting.repost_ratio > 0 and random.random() < self.config.posting.repost_ratio / self._sessions_per_day):
                ok = self.client.repost(post.uri, post.cid)
                log_action(
                    session=db,
                    bot_id=self.config.bot_id,
                    action_type="repost",
                    target_uri=post.uri,
                    seen_post_id=seen_rec.id,
                    success=ok,
                )
                if ok:
                    summary["reposts"] += 1

        self._maybe_follow(db, summary, liked_authors)

    def _maybe_follow(self, db: DbSession, summary: dict, liked_authors: dict[str, int]) -> None:
        """Follow authors who hit the follow_trigger_likes threshold."""
        cfg = self.config.follow
        current_following = {p.did for p in self.client.get_following()}
        follows_done = 0

        for did, like_count in liked_authors.items():
            if not did:
                continue
            if follows_done >= cfg.daily_follow_max:
                break
            if len(current_following) + follows_done >= cfg.max_follows:
                break
            if did in current_following:
                continue
            if like_count < cfg.follow_trigger_likes:
                continue

            ok = self.client.follow(did)
            log_action(
                session=db,
                bot_id=self.config.bot_id,
                action_type="follow",
                target_did=did,
                success=ok,
            )
            if ok:
                follows_done += 1
                summary["follows"] += 1

    #  ---------------------------------------------------------------------------
    #  Private - post generation
    #  ---------------------------------------------------------------------------

    def _maybe_post(self, db: DbSession, summary: dict) -> None:
        """Generate and publish original posts if this bot is a poster."""
        if self.generator is None or self.config.posting.posts_per_day == 0:
            return

        #  Expected original posts this session
        expected = (self.config.posting.posts_per_day * self.config.posting.original_ratio / self._sessions_per_day)

        n_posts = int(expected)
        if random.random() < (expected - n_posts):
            n_posts += 1

        recent_topics = summary.get("recent_topics", [])

        for _ in range(n_posts):
            gen_rec = self.generator.generate(
                session=db,
                recent_topics=recent_topics,
            )
            if gen_rec is None:
                continue
            uri = self.client.create_post(gen_rec.text)
            if uri:
                gen_rec.uri = uri
                gen_rec.posted_at = datetime.now(timezone.utc)
                log_action(
                    session=db,
                    bot_id=self.config.bot_id,
                    action_type="post",
                    target_uri=uri,
                    success=True,
                )
                summary["posts"] += 1

    #  ---------------------------------------------------------------------------
    #  Private - helpers
    #  ---------------------------------------------------------------------------

    def _get_seen_uris(self, db: DbSession) -> set[str]:
        """Load all URIs this bot has already seen (avoids duplicates)."""
        rows = (
            db.query(SeenPost.uri)
            .filter(SeenPost.bot_id == self.config.bot_id)
            .all()
        )
        return {r.uri for r in rows}
