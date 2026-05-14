from dataclasses import dataclass
#  TODO - consider adding bot that spreads rumors or leaks in tech
 
#  ---------------------------------------------------------------------------
#  constants
#  ---------------------------------------------------------------------------
 
SIMULATION_DURATION_WEEKS = 8

#  random offset session start
SESSION_JITTER_MINUTES = 5

FEED_FETCH_LIMIT = 50

GRAPH_SNAPSHOT_DAY = 0
 
 
#  ---------------------------------------------------------------------------
#  dataclasses
#  ---------------------------------------------------------------------------
 
@dataclass
class Schedule:
    """
    session schedule for the bots
    session_hours: list of (hour, minute) tuples for when sessions fire.
    active_window: (start_hour, end_hour) outside which no actions are taken.
    """
    session_hours: list[tuple[int, int]]
    active_window: tuple[int, int]
    spike_enabled: bool = False         #  if bot reacts to trending content
 
 
@dataclass
class PostingBehavior:
    """
    how a bot produces content
    posts_per_day = 0 for consumers
    """
    posts_per_day: int
    original_ratio: float               #  how many are LLM-generated
    repost_ratio: float                 #  how many are reposts
    reply_rate: float                   #  probability of replying to a seen post
 
 
@dataclass
class ConsumptionBehavior:
    """
    how a bot reads and reacts to content
    """
    likes_per_day: tuple[int, int]               #  (min, max) likes per day
    cosine_threshold: float                      #  minimum similarity to act on a post
    engagement_weight: float                     #  0.0-1.0, how much engagement score influences decisions
    language_filter: str | None = None
    source_filter: str = "any"                   #  "any" | "verified_only"
 
 
@dataclass
class FollowBehavior:
    """
    Defines how a bot builds its follow graph
    """
    daily_follow_min: int
    daily_follow_max: int
    max_follows: int
    follow_trigger_likes: int           #  how many liked posts from one account before following
    unfollow_inactive_days: int         #  unfollow if no relevant post in N days
    strategy_weights: dict              #  {"keyword": 0.6, "graph_mirror": 0.3, "engager": 0.1}
 
 
@dataclass
class BotConfig:
    """
    Complete configuration for a single bot
    """
    bot_id: str
    display_name: str
    profile_id: int
    persona_prompt: str                 #  LLM prompt for post generation
    interest_topics: list[str]          #  topics for interest vector
    schedule: Schedule
    posting: PostingBehavior
    consumption: ConsumptionBehavior
    follow: FollowBehavior
    bluesky_handle: str = ""            #  TODO set when I create accounts!!!!
    bluesky_password: str = ""          #  TODO set when I create accounts!!!!
 
 
#  ---------------------------------------------------------------------------
#  profile 1
#  ---------------------------------------------------------------------------
 
BOT_1A = BotConfig(
    bot_id="1A",
    display_name="Bot 1A",
    profile_id=1,
    persona_prompt=(
        "You are a passionate political activist. "
        "Write a short Bluesky post (max 280 chars) about {topic}. "
        "Use strong conviction. Include 1-2 relevant hashtags."
    ),
    interest_topics=[
        "climate policy",
        "human rights",
        "electoral politics",
        "protest movements",
        "social justice",
    ],
    schedule=Schedule(
        session_hours=[(7, 30), (12, 30), (20, 0)],
        active_window=(7, 23),
        spike_enabled=True,
    ),
    posting=PostingBehavior(
        posts_per_day=5,                #  midpoint of 4-6
        original_ratio=0.70,
        repost_ratio=0.30,
        reply_rate=0.25,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(8, 15),
        cosine_threshold=0.75,
        engagement_weight=0.2,
    ),
    follow=FollowBehavior(
        daily_follow_min=2,
        daily_follow_max=5,
        max_follows=300,
        follow_trigger_likes=3,
        unfollow_inactive_days=14,
        strategy_weights={"keyword": 0.60, "graph_mirror": 0.30, "engager": 0.10},
    ),
)
 
BOT_1B = BotConfig(
    bot_id="1B",
    display_name="Bot 1B",
    profile_id=1,
    persona_prompt=(
        "You are a quiet political supporter. "
        "Write a brief Bluesky post (max 180 chars) sharing your view on {topic}. "
        "Understated tone. No hashtags."
    ),
    interest_topics=[
        "climate policy",
        "human rights",
        "electoral politics",
        "protest movements",
        "social justice",
    ],
    schedule=Schedule(
        session_hours=[(12, 0), (20, 30)],
        active_window=(8, 22),
        spike_enabled=True,
    ),
    posting=PostingBehavior(
        posts_per_day=2,
        original_ratio=0.15,
        repost_ratio=0.85,
        reply_rate=0.05,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(5, 10),
        cosine_threshold=0.65,
        engagement_weight=0.5,          #  more influenced by engagement than 1A
    ),
    follow=FollowBehavior(
        daily_follow_min=2,
        daily_follow_max=5,
        max_follows=300,
        follow_trigger_likes=3,
        unfollow_inactive_days=14,
        strategy_weights={"keyword": 0.60, "graph_mirror": 0.30, "engager": 0.10},
    ),
)
 
BOT_1C = BotConfig(
    bot_id="1C",
    display_name="Bot 1C",
    profile_id=1,
    persona_prompt="",                  #  never posts
    interest_topics=[
        "climate policy",
        "human rights",
        "electoral politics",
        "protest movements",
        "social justice",
    ],
    schedule=Schedule(
        session_hours=[(7, 30), (12, 30), (19, 30)],
        active_window=(7, 22),
        spike_enabled=False,
    ),
    posting=PostingBehavior(
        posts_per_day=0,
        original_ratio=0.0,
        repost_ratio=0.0,
        reply_rate=0.0,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(8, 15),
        cosine_threshold=0.65,
        engagement_weight=0.3,
    ),
    follow=FollowBehavior(
        daily_follow_min=1,
        daily_follow_max=3,
        max_follows=200,
        follow_trigger_likes=3,
        unfollow_inactive_days=14,
        strategy_weights={"keyword": 0.60, "graph_mirror": 0.30, "engager": 0.10},
    ),
)
 
 
#  ---------------------------------------------------------------------------
#  Profile 2 - The Tech Enthusiast
#  ---------------------------------------------------------------------------
 
BOT_2A = BotConfig(
    bot_id="2A",
    display_name="Bot 2A",
    profile_id=2,
    persona_prompt=(
        "You are a tech-savvy enthusiast interested in software, gaming, gadgets "
        "and emerging technology. Write a thoughtful Bluesky post (max 280 chars) "
        "about {topic}. Be precise and opinionated but not inflammatory. "
        "May reference a specific tool, game, or technology."
    ),
    interest_topics=[
        "open source",
        "programming",
        "gaming",
        "new technologies",
        "gadgets and hardware",
        "AI and machine learning",
        "space exploration",
        "cybersecurity",
    ],
    schedule=Schedule(
        session_hours=[(8, 30), (12, 0), (20, 0)],
        active_window=(8, 22),
        spike_enabled=True,
    ),
    posting=PostingBehavior(
        posts_per_day=3,
        original_ratio=0.55,
        repost_ratio=0.45,
        reply_rate=0.20,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(8, 15),
        cosine_threshold=0.72,
        engagement_weight=0.3,
    ),
    follow=FollowBehavior(
        daily_follow_min=3,
        daily_follow_max=6,
        max_follows=400,
        follow_trigger_likes=2,
        unfollow_inactive_days=10,
        strategy_weights={"keyword": 0.75, "graph_mirror": 0.15, "engager": 0.10},
    ),
)
 
BOT_2B = BotConfig(
    bot_id="2B",
    display_name="Bot 2B",
    profile_id=2,
    persona_prompt=(
        "You are an enthusiastic tech and gaming follower. "
        "Write a very short, excited Bluesky post (max 140 chars) reacting to {topic}. "
        "Keep it punchy. One sentence max. No hashtags needed."
    ),
    interest_topics=[
        "open source",
        "programming",
        "gaming",
        "new technologies",
        "gadgets and hardware",
        "AI and machine learning",
        "space exploration",
        "cybersecurity",
    ],
    schedule=Schedule(
        session_hours=[(9, 0), (13, 0), (17, 0), (20, 30)],
        active_window=(9, 22),
        spike_enabled=True,
    ),
    posting=PostingBehavior(
        posts_per_day=6,
        original_ratio=0.20,
        repost_ratio=0.80,
        reply_rate=0.08,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(10, 20),
        cosine_threshold=0.58,
        engagement_weight=0.60,         #  heavily engagement-driven
    ),
    follow=FollowBehavior(
        daily_follow_min=3,
        daily_follow_max=6,
        max_follows=400,
        follow_trigger_likes=2,
        unfollow_inactive_days=10,
        strategy_weights={"keyword": 0.75, "graph_mirror": 0.15, "engager": 0.10},
    ),
)
 
BOT_2C = BotConfig(
    bot_id="2C",
    display_name="Bot 2C",
    profile_id=2,
    persona_prompt="",                  #  never posts
    interest_topics=[
        "open source",
        "programming",
        "gaming",
        "new technologies",
        "gadgets and hardware",
        "AI and machine learning",
        "space exploration",
        "cybersecurity",
    ],
    schedule=Schedule(
        session_hours=[(8, 30), (12, 30), (20, 0)],
        active_window=(8, 22),
        spike_enabled=False,
    ),
    posting=PostingBehavior(
        posts_per_day=0,
        original_ratio=0.0,
        repost_ratio=0.0,
        reply_rate=0.0,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(10, 20),
        cosine_threshold=0.62,
        engagement_weight=0.4,
    ),
    follow=FollowBehavior(
        daily_follow_min=2,
        daily_follow_max=4,
        max_follows=250,
        follow_trigger_likes=2,
        unfollow_inactive_days=10,
        strategy_weights={"keyword": 0.75, "graph_mirror": 0.15, "engager": 0.10},
    ),
)
 
 
#  ---------------------------------------------------------------------------
#  Profile 3 - The News Consumer
#  ---------------------------------------------------------------------------
 
BOT_3A = BotConfig(
    bot_id="3A",
    display_name="Bot 3A",
    profile_id=3,
    persona_prompt="",                  #  never posts
    interest_topics=[
        "trending",
        "viral content",
        "pop culture",
        "breaking news",
    ],
    schedule=Schedule(
        session_hours=[(8, 0), (12, 30), (19, 30)],
        active_window=(8, 23),
        spike_enabled=True,
    ),
    posting=PostingBehavior(
        posts_per_day=0,
        original_ratio=0.0,
        repost_ratio=0.0,
        reply_rate=0.0,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(10, 20),
        cosine_threshold=0.0,           #  no topic filter - engagement only
        engagement_weight=0.80,
    ),
    follow=FollowBehavior(
        daily_follow_min=1,
        daily_follow_max=2,
        max_follows=150,
        follow_trigger_likes=2,
        unfollow_inactive_days=21,
        strategy_weights={"keyword": 0.30, "graph_mirror": 0.40, "engager": 0.30},
    ),
)
 
BOT_3B = BotConfig(
    bot_id="3B",
    display_name="Bot 3B",
    profile_id=3,
    persona_prompt="",                  #  never posts
    interest_topics=[
        "world politics",
        "economy",
        "science",
        "verified news outlets",
    ],
    schedule=Schedule(
        session_hours=[(7, 30), (12, 30), (18, 30)],
        active_window=(7, 22),
        spike_enabled=False,
    ),
    posting=PostingBehavior(
        posts_per_day=0,
        original_ratio=0.0,
        repost_ratio=0.0,
        reply_rate=0.0,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(5, 10),
        cosine_threshold=0.60,
        engagement_weight=0.2,
        source_filter="verified_only",  #  only interacts with verified accounts
    ),
    follow=FollowBehavior(
        daily_follow_min=0,
        daily_follow_max=1,
        max_follows=150,
        follow_trigger_likes=3,
        unfollow_inactive_days=21,
        strategy_weights={"keyword": 0.50, "graph_mirror": 0.40, "engager": 0.10},
    ),
)
 
BOT_3C = BotConfig(
    bot_id="3C",
    display_name="Bot 3C",
    profile_id=3,
    persona_prompt="",                  #  never posts
    interest_topics=[
        "slovensko",
        "spravy",
        "politika SK",
        "regionalne spravy",
    ],
    schedule=Schedule(
        session_hours=[(6, 30), (12, 0), (19, 30)],
        active_window=(6, 21),
        spike_enabled=False,
    ),
    posting=PostingBehavior(
        posts_per_day=0,
        original_ratio=0.0,
        repost_ratio=0.0,
        reply_rate=0.0,
    ),
    consumption=ConsumptionBehavior(
        likes_per_day=(3, 8),
        cosine_threshold=0.58,
        engagement_weight=0.3,
        language_filter="sk",           #  only interacts with Slovak content
    ),
    follow=FollowBehavior(
        daily_follow_min=0,
        daily_follow_max=1,
        max_follows=150,
        follow_trigger_likes=3,
        unfollow_inactive_days=21,
        strategy_weights={"keyword": 0.70, "graph_mirror": 0.20, "engager": 0.10},
    ),
)
 
 
#  ---------------------------------------------------------------------------
#  bot registry
#  ---------------------------------------------------------------------------
 
ALL_BOTS: list[BotConfig] = [
    BOT_1A, BOT_1B, BOT_1C,
    BOT_2A, BOT_2B, BOT_2C,
    BOT_3A, BOT_3B, BOT_3C,
]
 
BOTS_BY_ID: dict[str, BotConfig] = {bot.bot_id: bot for bot in ALL_BOTS}
 
PROFILE_1_BOTS: list[BotConfig] = [BOT_1A, BOT_1B, BOT_1C]
PROFILE_2_BOTS: list[BotConfig] = [BOT_2A, BOT_2B, BOT_2C]
PROFILE_3_BOTS: list[BotConfig] = [BOT_3A, BOT_3B, BOT_3C]
 
CONSUMER_BOTS: list[BotConfig] = [BOT_1C, BOT_2C, BOT_3A, BOT_3B, BOT_3C]
POSTING_BOTS: list[BotConfig] = [BOT_1A, BOT_1B, BOT_2A, BOT_2B]