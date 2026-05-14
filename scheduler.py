import logging
import math
import random
from datetime import date

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from config import GRAPH_SNAPSHOT_DAY, SESSION_JITTER_MINUTES
from storage import save_feed_snapshot, save_graph_snapshot

log = logging.getLogger(__name__)


#  ---------------------------------------------------------------------------
#  Scheduled jobs
#  ---------------------------------------------------------------------------

def _session_job(bot) -> None:
    try:
        bot.run_session()
    except Exception:
        log.exception("Unhandled error in session job for %s", bot.config.bot_id)


def _feed_snapshot_job(bot, db_factory) -> None:
    from sqlalchemy import func
    from storage import SeenPost

    week = _current_week()
    db = db_factory()
    try:
        rows = (
            db.query(SeenPost.topic, func.count(SeenPost.id))
            .filter(SeenPost.bot_id == bot.config.bot_id)
            .group_by(SeenPost.topic)
            .all()
        )
        topic_counts = {(topic or "other"): count for topic, count in rows}
        total = sum(topic_counts.values())

        entropy = 0.0
        if total > 0:
            for count in topic_counts.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log2(p)

        avg_cosine_raw = (
            db.query(func.avg(SeenPost.cosine_score))
            .filter(SeenPost.bot_id == bot.config.bot_id)
            .scalar()
        )
        avg_cosine = float(avg_cosine_raw) if avg_cosine_raw is not None else 0.0

        save_feed_snapshot(
            session=db,
            bot_id=bot.config.bot_id,
            week_number=week,
            topic_counts=topic_counts,
            entropy=entropy,
            avg_cosine=avg_cosine,
            total_posts_seen=total,
        )
        db.commit()
        log.info(
            "[%s] Feed snapshot wk%d: entropy=%.3f avg_cosine=%.3f posts=%d",
            bot.config.bot_id, week, entropy, avg_cosine, total,
        )
    except Exception:
        db.rollback()
        log.exception("[%s] Feed snapshot failed", bot.config.bot_id)
    finally:
        db.close()


def _graph_snapshot_job(bot, db_factory) -> None:
    """
    Weekly follow-graph snapshot.
    Captures following/follower counts and stores the list of followed DIDs
    for later homophily and degree-distribution analysis.
    """
    week = _current_week()
    following = bot.client.get_following()
    followers = bot.client.get_followers()
    homophily = 0.0

    db = db_factory()
    try:
        save_graph_snapshot(
            session=db,
            bot_id=bot.config.bot_id,
            week_number=week,
            following_count=len(following),
            followers_count=len(followers),
            homophily_score=homophily,
            following_dids=[p.did for p in following],
        )
        db.commit()
        log.info(
            "[%s] Graph snapshot wk%d: following=%d followers=%d",
            bot.config.bot_id, week, len(following), len(followers),
        )
    except Exception:
        db.rollback()
        log.exception("[%s] Graph snapshot failed", bot.config.bot_id)
    finally:
        db.close()


#  ---------------------------------------------------------------------------
#  Builder
#  ---------------------------------------------------------------------------

def build_scheduler(bots: list, db_factory) -> BackgroundScheduler:
    """
    Build and return an APScheduler BackgroundScheduler with all jobs wired.
    Each bot session gets a random offset of SESSION_JITTER_MINUTES so
    all bots don't fire simultaneously even if their times overlap.
    """
    n_workers = len(bots) + 4
    executors = {"default": ThreadPoolExecutor(max_workers=n_workers)}
    scheduler = BackgroundScheduler(executors=executors, timezone="UTC")

    for bot in bots:
        for hour, minute in bot.config.schedule.session_hours:
            jitter = random.randint(-SESSION_JITTER_MINUTES, SESSION_JITTER_MINUTES)
            jittered = max(0, min(59, minute + jitter))

            scheduler.add_job(
                _session_job,
                trigger="cron",
                hour=hour,
                minute=jittered,
                args=[bot],
                id=f"session_{bot.config.bot_id}_{hour:02d}{minute:02d}",
                name=f"{bot.config.bot_id} session {hour:02d}:{jittered:02d}",
                misfire_grace_time=300,
            )
            log.info(
                "Scheduled %s session at %02d:%02d (jitter %+d min)",
                bot.config.bot_id, hour, jittered, jitter,
            )

        scheduler.add_job(
            _feed_snapshot_job,
            trigger="cron",
            day_of_week=GRAPH_SNAPSHOT_DAY,
            hour=2,
            minute=0,
            args=[bot, db_factory],
            id=f"feed_snap_{bot.config.bot_id}",
            name=f"{bot.config.bot_id} weekly feed snapshot",
            misfire_grace_time=3600,
        )

        scheduler.add_job(
            _graph_snapshot_job,
            trigger="cron",
            day_of_week=GRAPH_SNAPSHOT_DAY,
            hour=2,
            minute=30,
            args=[bot, db_factory],
            id=f"graph_snap_{bot.config.bot_id}",
            name=f"{bot.config.bot_id} weekly graph snapshot",
            misfire_grace_time=3600,
        )

    total_session_jobs = sum(len(b.config.schedule.session_hours) for b in bots)
    log.info(
        "Scheduler built: %d session jobs + %d snapshot jobs for %d bots",
        total_session_jobs, len(bots) * 2, len(bots),
    )
    return scheduler


#  ---------------------------------------------------------------------------
#  Helper
#  ---------------------------------------------------------------------------

def _current_week() -> int:
    """Return the ISO week number of the current date."""
    return date.today().isocalendar()[1]
