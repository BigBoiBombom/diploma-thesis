# Filter Bubble Simulation

A bot-driven simulation of filter bubble formation on Bluesky. Nine bots with distinct personas and interest profiles run for ~8 weeks, and their feed composition is measured weekly to observe if and how quickly algorithmic personalisation creates isolation of topics and ideas.

---

## Research question

Do filter bubbles form naturally through passive consumption alone, or does active posting and engagement accelerate the process? And can targeted disruption strategies break them?

---

## Bot profiles

Three profiles, three bots each (A = active poster, B = amplifier/reposter, C = passive consumer).

| Bot | Role | Domain | Cosine threshold |
|-----|------|--------|-----------------|
| 1A | Original poster | Politics & social justice | 0.75 |
| 1B | Reposter | Politics & social justice | 0.65 |
| 1C | Pure consumer | Politics & social justice | 0.65 |
| 2A | Original poster | Tech, gaming & science | 0.72 |
| 2B | Reposter | Tech, gaming & science | 0.58 |
| 2C | Pure consumer | Tech, gaming & science | 0.62 |
| 3A | Pure consumer | Trending / viral | 0.0 |
| 3B | Pure consumer | News (verified only) | 0.60 |
| 3C | Pure consumer | Slovak-language content | 0.58 |

Key experiments embedded in the design:
- **1A vs 1C**: does passive consumption form as tight a bubble as active posting?
- **3A**: anchor-free bot, tracks wherever the algorithm naturally drifts it over 8 weeks
- **3C**: language-enforced bubble, tests whether language isolates as strongly as ideology

---

## Architecture

```
diploma-thesis/
├── main.py          Entry point - wires all modules, starts the simulation
├── config.py        All 9 bot profiles as dataclasses, simulation constants
├── bluesky.py       Bluesky API wrapper
├── content.py       Cosine scoring engine, language detection, topic labelling
├── generator.py     LLM post generation via Claude Haiku (Anthropic API)
├── bot.py           Core session loop - fetch, score, act, post, commit
├── scheduler.py     APScheduler wiring - session jobs + weekly snapshots
├── storage.py       SQLAlchemy ORM - 5 tables, SQLite backend
└── data/            Auto-created — simulation.db + simulation.log
```

---

## How it works

### Session loop (per bot, per scheduled time)
1. Fetch posts from the Bluesky timeline
2. Score each post - cosine similarity against the bot's interest vector + normalised engagement score
3. Log every seen post to the database (needed for entropy analysis regardless of outcome)
4. Like posts that pass the filter and are within the session budget
5. Repost with probability derived from the bot's `repost_ratio`
6. Follow authors who received enough likes from this bot (`follow_trigger_likes`)
7. Generate and publish original posts (posting bots only) using Claude Haiku (may change LLM)
8. Commit the entire DB transaction

### Scoring
Each post gets a final score: `final = (1 - engagement_weight) × cosine + engagement_weight × engagement`

- **Cosine score**: semantic similarity between the post and the bot's interest embedding (all-MiniLM-L6-v2)
- **Engagement score**: log-normalised like/repost counts (capped at 500 likes / 200 reposts)
- **`engagement_weight`** varies per bot: Bot 3A is 0.8 (almost pure engagement), Bot 1A is 0.2 (almost pure cosine)

### Measurement
Two snapshots are written every Monday:

- **FeedSnapshot**: Shannon entropy of topic distribution + average cosine score for the week. Entropy should drop and cosine should rise as a bubble forms.
- **GraphSnapshot**: following/follower counts + full list of followed DIDs. Used in the analysis phase to check for power-law degree distribution, which is the structural signature of a real filter bubble.

---

## Literature

- Burbach et al. (2019): Bubble Trouble: Strategies Against Filter Bubbles in Online Social Networks - https://calerovaldez.com/pdf/burbach2019bubble.pdf
- Min et al. (2019)​: Weibo bot study - power-law degree distribution and unidirectional star topology as structural bubble signatures - https://pmc.ncbi.nlm.nih.gov/articles/PMC6894573/
- Einav et al. (2022): repeated exposure (not single encounters) required for disruption - https://www.sciencedirect.com/science/article/pii/S0160791X22002779
