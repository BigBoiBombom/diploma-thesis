import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

_data_dir = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(_data_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "data", "simulation.log")),
    ],
)
log = logging.getLogger("main")


from config import ALL_BOTS, POSTING_BOTS
from storage import init_db
from bluesky import build_client
from content import ContentScorer
from generator import PostGenerator
from bot import Bot
from scheduler import build_scheduler


#  ---------------------------------------------------------------------------
#  environment
#  ---------------------------------------------------------------------------

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        log.warning(".env file not found at %s - bot credentials will be missing", env_path)
        return
    load_dotenv(env_path)
    log.info("Environment loaded from %s", env_path)


def get_bot_credentials(bot_id: str) -> tuple[str, str]:
    """get handle + password for a bot from environment variables"""
    key = bot_id.replace("-", "_").upper()
    handle = os.getenv(f"BOT_{key}_HANDLE")
    password = os.getenv(f"BOT_{key}_PASSWORD")
    if not handle or not password:
        raise EnvironmentError(
            f"Missing credentials for bot {bot_id}. "
            f"Expected BOT_{key}_HANDLE and BOT_{key}_PASSWORD in .env"
        )
    return handle, password


#  ---------------------------------------------------------------------------
#  checks
#  ---------------------------------------------------------------------------

def check_environment():
    missing = []
    for bot in ALL_BOTS:
        key = bot.bot_id.replace("-", "_").upper()
        if not os.getenv(f"BOT_{key}_HANDLE"):
            missing.append(f"BOT_{key}_HANDLE")
        if not os.getenv(f"BOT_{key}_PASSWORD"):
            missing.append(f"BOT_{key}_PASSWORD")

    if missing:
        log.error("Missing environment variables:\n  %s", "\n  ".join(missing))
        sys.exit(1)

    log.info("Environment check passed - credentials found for %d bots", len(ALL_BOTS))


def check_data_directory():
    """check the data/ directory or create if it doesn't exist"""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    log.info("Data directory ready at %s", data_dir)


#  ---------------------------------------------------------------------------
#  shutdown
#  ---------------------------------------------------------------------------

def register_shutdown(loop: asyncio.AbstractEventLoop, scheduler=None):
    def _shutdown(signum, _frame):
        log.info("Received signal %s - shutting down simulation...", signum)
        if scheduler:
            scheduler.shutdown(wait=False)
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)


#  ---------------------------------------------------------------------------
#  main
#  ---------------------------------------------------------------------------

USE_MOCK = True  #  TODO set to False when accounts are ready


async def main():
    log.info("Starting simulation (mock=%s)...", USE_MOCK)

    #  1. Load environment
    load_env()
    check_environment()
    check_data_directory()

    #  2. Initialise database
    db_path = os.path.join(os.path.dirname(__file__), "data", "simulation.db")
    db_factory = init_db(db_path)

    #  3. Load embedding model
    scorer = ContentScorer()
    scorer.load_model()

    #  4. Build Bot instances
    bots: list[Bot] = []
    posting_bot_ids = {b.bot_id for b in POSTING_BOTS}

    for bot_cfg in ALL_BOTS:
        handle, password = get_bot_credentials(bot_cfg.bot_id)
        bot_cfg.bluesky_handle = handle
        bot_cfg.bluesky_password = password

        #  Pick a topic hint for the mock client feed bias
        topic_hint = bot_cfg.interest_topics[0] if bot_cfg.interest_topics else None
        client = build_client(
            handle=handle,
            password=password,
            mock=USE_MOCK,
            topic_hint=topic_hint,
        )
        client.login()

        interest_embedding = scorer.embed_interests(bot_cfg.interest_topics)

        generator = None
        if bot_cfg.bot_id in posting_bot_ids:
            generator = PostGenerator(bot=bot_cfg, mock=USE_MOCK)

        bot = Bot(
            config=bot_cfg,
            db_factory=db_factory,
            client=client,
            scorer=scorer,
            interest_embedding=interest_embedding,
            generator=generator,
        )
        bots.append(bot)

    log.info("Initialised %d bots (%d posting)", len(bots), len(posting_bot_ids))

    if USE_MOCK:
        #  5. Mock mode: run one session per bot and exit
        log.info("Mock mode: running one session per bot then stopping.")
        for bot in bots:
            bot.run_session()
        log.info("Mock run complete.")
        return

    #  5. Production: build and start scheduler
    scheduler = build_scheduler(bots=bots, db_factory=db_factory)

    loop = asyncio.get_running_loop()
    register_shutdown(loop, scheduler)

    scheduler.start()
    log.info("Scheduler started - simulation running. Press Ctrl+C to stop.")

    #  6. Keep the event loop alive until shutdown signal
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)
        log.info("Simulation stopped.")


if __name__ == "__main__":
    asyncio.run(main())
