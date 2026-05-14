import json
import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, Integer, String, Text,
    create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

log = logging.getLogger(__name__)


#  ---------------------------------------------------------------------------
#  ORM base
#  ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


#  ---------------------------------------------------------------------------
#  Tables
#  ---------------------------------------------------------------------------

class SeenPost(Base):
    """Every post seen in a bot's feed."""
    __tablename__ = "seen_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    uri: Mapped[str] = mapped_column(String(200), nullable=False)
    cid: Mapped[str] = mapped_column(String(100), nullable=False)
    author_did: Mapped[str] = mapped_column(String(100), nullable=False)
    author_handle: Mapped[str] = mapped_column(String(100), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    post_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cosine_score: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    passed_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    topic: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Action(Base):
    """Every action a bot executes."""
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    #  action_type: like | repost | follow | unfollow | post | reply
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_uri: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_did: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seen_post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True)


class GeneratedPost(Base):
    """LLM-generated post."""
    __tablename__ = "generated_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    topic_seed: Mapped[str | None] = mapped_column(String(200), nullable=True)
    uri: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)


class FeedSnapshot(Base):
    """Weekly entropy snapshot of what a bot has been seeing."""
    __tablename__ = "feed_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    _topic_counts_json: Mapped[str] = mapped_column("topic_counts_json", Text, default="{}")
    entropy: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cosine: Mapped[float] = mapped_column(Float, default=0.0)
    total_posts_seen: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def topic_counts(self) -> dict:
        return json.loads(self._topic_counts_json)

    @topic_counts.setter
    def topic_counts(self, value: dict) -> None:
        self._topic_counts_json = json.dumps(value)


class GraphSnapshot(Base):
    """Weekly follow-graph state for a bot."""
    __tablename__ = "graph_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    homophily_score: Mapped[float] = mapped_column(Float, default=0.0)
    _following_dids_json: Mapped[str] = mapped_column("following_dids_json", Text, default="[]")

    @property
    def following_dids(self) -> list:
        return json.loads(self._following_dids_json)

    @following_dids.setter
    def following_dids(self, value: list) -> None:
        self._following_dids_json = json.dumps(value)


#  ---------------------------------------------------------------------------
#  Initialisation
#  ---------------------------------------------------------------------------

def init_db(db_path: str) -> sessionmaker:
    """
    Create engine, enable WAL mode, create all tables.
    Returns a sessionmaker - call once in main.py.
    """
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA synchronous=NORMAL")

    Base.metadata.create_all(engine)
    log.info("Database initialised at %s", db_path)
    return sessionmaker(bind=engine)


#  ---------------------------------------------------------------------------
#  Write helpers
#  All use flush() not commit() - bot.py commits the full session.
#  ---------------------------------------------------------------------------

def log_seen_post(
    session: Session,
    bot_id: str,
    uri: str,
    cid: str,
    author_did: str,
    author_handle: str,
    text: str,
    post_created_at: datetime,
    cosine_score: float,
    engagement_score: float,
    final_score: float,
    language: str | None,
    passed_filter: bool,
    topic: str | None,
) -> SeenPost:
    record = SeenPost(
        bot_id=bot_id,
        uri=uri,
        cid=cid,
        author_did=author_did,
        author_handle=author_handle,
        text=text,
        post_created_at=post_created_at,
        seen_at=datetime.now(timezone.utc),
        cosine_score=cosine_score,
        engagement_score=engagement_score,
        final_score=final_score,
        language=language,
        passed_filter=passed_filter,
        topic=topic,
    )
    session.add(record)
    session.flush()
    return record


def log_action(
    session: Session,
    bot_id: str,
    action_type: str,
    target_uri: str | None = None,
    target_did: str | None = None,
    seen_post_id: int | None = None,
    success: bool = True,
) -> Action:
    record = Action(
        bot_id=bot_id,
        action_type=action_type,
        target_uri=target_uri,
        target_did=target_did,
        seen_post_id=seen_post_id,
        timestamp=datetime.now(timezone.utc),
        success=success,
    )
    session.add(record)
    session.flush()
    return record


def log_generated_post(
    session: Session,
    bot_id: str,
    text: str,
    topic_seed: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> GeneratedPost:
    record = GeneratedPost(
        bot_id=bot_id,
        text=text,
        topic_seed=topic_seed,
        generated_at=datetime.now(timezone.utc),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    session.add(record)
    session.flush()
    return record


def save_feed_snapshot(
    session: Session,
    bot_id: str,
    week_number: int,
    topic_counts: dict,
    entropy: float,
    avg_cosine: float,
    total_posts_seen: int,
) -> FeedSnapshot:
    record = FeedSnapshot(
        bot_id=bot_id,
        snapshot_at=datetime.now(timezone.utc),
        week_number=week_number,
        entropy=entropy,
        avg_cosine=avg_cosine,
        total_posts_seen=total_posts_seen,
    )
    record.topic_counts = topic_counts
    session.add(record)
    session.flush()
    return record


def save_graph_snapshot(
    session: Session,
    bot_id: str,
    week_number: int,
    following_count: int,
    followers_count: int,
    homophily_score: float,
    following_dids: list,
) -> GraphSnapshot:
    record = GraphSnapshot(
        bot_id=bot_id,
        snapshot_at=datetime.now(timezone.utc),
        week_number=week_number,
        following_count=following_count,
        followers_count=followers_count,
        homophily_score=homophily_score,
    )
    record.following_dids = following_dids
    session.add(record)
    session.flush()
    return record
