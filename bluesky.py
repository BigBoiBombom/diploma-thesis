import logging
import random
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atproto import Client as AtprotoClient

log = logging.getLogger(__name__)


#  ---------------------------------------------------------------------------
#  Data transfer objects
#  ---------------------------------------------------------------------------

@dataclass
class BSkyPost:
    """A post in a bot's feed."""
    uri: str
    cid: str
    author_did: str
    author_handle: str
    text: str
    created_at: datetime
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    is_verified: bool = False
    language: str | None = None


@dataclass
class BSkyProfile:  #  TODO maybe add follower/following counts and is_bot flag, check other useful data
    """Profile info for a followed/following account."""
    did: str
    handle: str
    display_name: str | None = None
    is_verified: bool = False


@dataclass
class FeedPage:
    """A page of posts returned from a feed fetch."""
    posts: list[BSkyPost] = field(default_factory=list)
    cursor: str | None = None


class BaseBlueSkyClient(ABC):

    @abstractmethod
    def login(self) -> bool:
        """Authenticate with Bluesky. True on success."""

    @abstractmethod
    def get_timeline(self, limit: int = 50, cursor: str | None = None) -> FeedPage:
        """Fetch the bot's home timeline."""

    @abstractmethod
    def like_post(self, uri: str, cid: str) -> bool:
        """Like a post. True on success."""

    @abstractmethod
    def repost(self, uri: str, cid: str) -> bool:
        """Repost a post. True on success."""

    @abstractmethod
    def create_post(self, text: str) -> str | None:
        """Publish a new post. Returns the URI on success, None on failure."""

    @abstractmethod
    def follow(self, did: str) -> bool:
        """Follow an account. True on success."""

    @abstractmethod
    def unfollow(self, did: str) -> bool:
        """Unfollow an account. True on success."""

    @abstractmethod
    def get_following(self) -> list[BSkyProfile]:
        """Return list of accounts this bot is following."""

    @abstractmethod
    def get_followers(self) -> list[BSkyProfile]:
        """Return list of accounts following this bot."""

    @abstractmethod
    def search_posts(self, query: str, limit: int = 25) -> list[BSkyPost]:
        """Search public posts by keyword."""

    @abstractmethod
    def get_profile(self, did: str) -> BSkyProfile | None:
        """Fetch a single profile by did."""


#  ---------------------------------------------------------------------------
#  Real client
#  ---------------------------------------------------------------------------

class BlueskyClient(BaseBlueSkyClient):
    def __init__(self, handle: str, password: str):
        self.handle = handle
        self.password = password
        self._client: "AtprotoClient | None" = None

    def _get_client(self) -> "AtprotoClient":
        """Return the authenticated client, raise if login was not called."""
        if self._client is None:
            raise RuntimeError(
                f"BlueskyClient for {self.handle} is not logged in. Call login() first."
            )
        return self._client

    def login(self) -> bool:
        try:
            from atproto import Client
            self._client = Client()
            self._client.login(self.handle, self.password)
            log.info("Logged in as %s", self.handle)
            return True
        except Exception as e:
            log.error("Login failed for %s: %s", self.handle, e)
            return False

    def get_timeline(self, limit: int = 50, cursor: str | None = None) -> FeedPage:
        try:
            resp = self._get_client().get_timeline(
                algorithm=None,
                cursor=cursor,
                limit=limit,
            )
            posts = [self._convert_post(f.post) for f in resp.feed if f.post]
            return FeedPage(posts=posts, cursor=getattr(resp, "cursor", None))
        except Exception as e:
            log.error("get_timeline failed: %s", e)
            return FeedPage()

    def like_post(self, uri: str, cid: str) -> bool:
        try:
            self._get_client().like(uri=uri, cid=cid)
            return True
        except Exception as e:
            log.error("like_post failed for %s: %s", uri, e)
            return False

    def repost(self, uri: str, cid: str) -> bool:
        try:
            self._get_client().repost(uri=uri, cid=cid)
            return True
        except Exception as e:
            log.error("repost failed for %s: %s", uri, e)
            return False

    def create_post(self, text: str) -> str | None:
        try:
            resp = self._get_client().send_post(text=text)
            log.info("Post published: %s", resp.uri)
            return resp.uri
        except Exception as e:
            log.error("create_post failed: %s", e)
            return None

    def follow(self, did: str) -> bool:
        try:
            self._get_client().follow(did)
            return True
        except Exception as e:
            log.error("follow failed for %s: %s", did, e)
            return False

    def unfollow(self, did: str) -> bool:
        try:
            self._get_client().delete_follow(did)
            return True
        except Exception as e:
            log.error("unfollow failed for %s: %s", did, e)
            return False

    def get_following(self) -> list[BSkyProfile]:
        try:
            resp = self._get_client().get_follows(actor=self.handle, limit=100)
            return [self._convert_profile(f) for f in resp.follows]
        except Exception as e:
            log.error("get_following failed: %s", e)
            return []

    def get_followers(self) -> list[BSkyProfile]:
        try:
            resp = self._get_client().get_followers(actor=self.handle, limit=100)
            return [self._convert_profile(f) for f in resp.followers]
        except Exception as e:
            log.error("get_followers failed: %s", e)
            return []

    def search_posts(self, query: str, limit: int = 25) -> list[BSkyPost]:
        try:
            resp = self._get_client().app.bsky.feed.search_posts(
                params={"q": query, "limit": limit}
            )
            return [self._convert_post(p) for p in resp.posts]
        except Exception as e:
            log.error("search_posts failed for query '%s': %s", query, e)
            return []

    def get_profile(self, did: str) -> BSkyProfile | None:
        try:
            resp = self._get_client().get_profile(actor=did)
            return self._convert_profile(resp)
        except Exception as e:
            log.error("get_profile failed for %s: %s", did, e)
            return None

    #  -- conversion helpers --

    def _convert_post(self, post) -> BSkyPost:
        record = getattr(post, "record", None)
        text = getattr(record, "text", "") if record else ""
        created_raw = getattr(record, "created_at", None) if record else None
        try:
            created_at = datetime.fromisoformat(
                created_raw.replace("Z", "+00:00")
            ) if created_raw else datetime.now(timezone.utc)
        except Exception:
            created_at = datetime.now(timezone.utc)

        author = getattr(post, "author", None)
        return BSkyPost(
            uri=post.uri,
            cid=post.cid,
            author_did=getattr(author, "did", ""),
            author_handle=getattr(author, "handle", ""),
            text=text,
            created_at=created_at,
            like_count=getattr(post, "like_count", 0) or 0,
            repost_count=getattr(post, "repost_count", 0) or 0,
            reply_count=getattr(post, "reply_count", 0) or 0,
        )

    def _convert_profile(self, profile) -> BSkyProfile:
        return BSkyProfile(
            did=profile.did,
            handle=profile.handle,
            display_name=getattr(profile, "display_name", None),
        )


#  ---------------------------------------------------------------------------
#  Mock client - only used for testing
#  ---------------------------------------------------------------------------
_MOCK_POSTS_BY_TOPIC = {
    "politics": [
        "The new climate bill passed with a narrow majority. Here's what it means for emissions targets.",
        "Electoral reform is back on the agenda after last month's contested results.",
        "Protests outside parliament today over proposed changes to social welfare policy.",
        "The opposition party released a counter-proposal on immigration reform.",
        "Local elections next month - turnout expected to be the lowest in decades.",
    ],
    "tech": [
        "Just tried the new open source LLM - honestly impressive for a 7B model.",
        "Rust is eating Python's lunch in systems programming. Change my mind.",
        "New GPU dropped today. Benchmark numbers are wild.",
        "The latest cybersecurity report shows ransomware attacks up 40% YoY.",
        "This new framework makes async Rust actually readable. Finally.",
    ],
    "gaming": [
        "The new expansion dropped and I haven't slept in 36 hours.",
        "Hot take: the original Mass Effect trilogy aged better than most modern RPGs.",
        "Indie game of the year is already decided and it's only March.",
        "The patch notes for this update are longer than most novels.",
        "Anyone else think procedural generation has gotten lazy recently?",
    ],
    "news": [
        "Breaking: central bank announces surprise interest rate decision.",
        "Scientists confirm fastest warming decade on record.",
        "Trade talks between major economies stalled again this week.",
        "New study links ultra-processed foods to cognitive decline.",
        "Infrastructure bill clears final legislative hurdle.",
    ],
    "slovak": [
        "Vláda schválila nový balík opatrení pre malé podniky.",
        "Bratislava plánuje rozšíriť sieť cyklodopravy do roku 2026.",
        "Slovensko zaznamenalo rekordný nárast turistov v lete.",
        "Nová štúdia hodnotí kvalitu vzdelávania na slovenských školách.",
        "Parlament dnes rokuje o novele zákona o zdravotnom poistení.",
    ],
}

_ALL_MOCK_TOPICS = list(_MOCK_POSTS_BY_TOPIC.keys())


def _fake_did() -> str:
    return f"did:plc:{uuid.uuid4().hex[:24]}"


def _fake_uri(did: str) -> str:
    return f"at://{did}/app.bsky.feed.post/{uuid.uuid4().hex[:13]}"


def _fake_cid() -> str:
    return f"bafyrei{uuid.uuid4().hex[:32]}"


def _make_mock_post(topic: str | None = None) -> BSkyPost:
    """Generate a single realistic-looking fake post."""
    if topic is None:
        topic = random.choice(_ALL_MOCK_TOPICS)
    texts = _MOCK_POSTS_BY_TOPIC.get(topic, _MOCK_POSTS_BY_TOPIC["news"])
    did = _fake_did()
    return BSkyPost(
        uri=_fake_uri(did),
        cid=_fake_cid(),
        author_did=did,
        author_handle=f"user{random.randint(100, 9999)}.bsky.social",
        text=random.choice(texts),
        created_at=datetime.now(timezone.utc),
        like_count=random.randint(0, 200),
        repost_count=random.randint(0, 50),
        reply_count=random.randint(0, 30),
        language="sk" if topic == "slovak" else "en",
    )


class MockBlueskyClient(BaseBlueSkyClient):
    """
    Fake Bluesky client for testing.
    """

    def __init__(self, handle: str, _password: str, topic_hint: str | None = None):
        self.handle = handle
        self.did = _fake_did()
        self.topic_hint = topic_hint
        self._following: list[BSkyProfile] = []
        self._followers: list[BSkyProfile] = []
        log.info("[MOCK] Client initialized for %s", handle)

    def login(self) -> bool:
        log.info("[MOCK] login() called for %s - always succeeds", self.handle)
        return True

    def get_timeline(self, limit: int = 50, cursor: str | None = None) -> FeedPage:
        posts = []
        for _ in range(limit):
            if self.topic_hint and random.random() < 0.6:
                post = _make_mock_post(topic=self.topic_hint)
            else:
                post = _make_mock_post()
            posts.append(post)
        time.sleep(random.uniform(0.05, 0.15))
        log.debug("[MOCK] get_timeline() returned %d posts for %s", len(posts), self.handle)
        return FeedPage(posts=posts, cursor=None)

    def like_post(self, uri: str, cid: str) -> bool:
        log.debug("[MOCK] like_post() %s", uri)
        return True

    def repost(self, uri: str, cid: str) -> bool:
        log.debug("[MOCK] repost() %s", uri)
        return True

    def create_post(self, text: str) -> str | None:
        uri = _fake_uri(self.did)
        log.info("[MOCK] create_post() for %s: %s", self.handle, text[:80])
        return uri

    def follow(self, did: str) -> bool:
        if not any(p.did == did for p in self._following):
            self._following.append(BSkyProfile(did=did, handle=f"followed_{did[:8]}.bsky.social"))
        log.debug("[MOCK] follow() %s", did)
        return True

    def unfollow(self, did: str) -> bool:
        self._following = [p for p in self._following if p.did != did]
        log.debug("[MOCK] unfollow() %s", did)
        return True

    def get_following(self) -> list[BSkyProfile]:
        return list(self._following)

    def get_followers(self) -> list[BSkyProfile]:
        #  generate fake followers
        return [
            BSkyProfile(did=_fake_did(), handle=f"follower{i}.bsky.social")
            for i in range(random.randint(0, 10))
        ]

    def search_posts(self, query: str, limit: int = 25) -> list[BSkyPost]:
        topic = self.topic_hint or random.choice(_ALL_MOCK_TOPICS)
        posts = [_make_mock_post(topic=topic) for _ in range(limit)]
        log.debug("[MOCK] search_posts('%s') returned %d posts", query, len(posts))
        return posts

    def get_profile(self, did: str) -> BSkyProfile | None:
        return BSkyProfile(did=did, handle=f"user_{did[:8]}.bsky.social")


#  ---------------------------------------------------------------------------
#  Factory — used by main.py to build the right client
#  ---------------------------------------------------------------------------

def build_client(
    handle: str,
    password: str,
    mock: bool = False,
    topic_hint: str | None = None,
) -> BaseBlueSkyClient:
    """
    Return MockBlueskyClient if mock=True, otherwise BlueskyClient.
    """
    if mock:
        return MockBlueskyClient(handle=handle, _password=password, topic_hint=topic_hint)
    return BlueskyClient(handle=handle, password=password)