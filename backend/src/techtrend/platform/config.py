"""Typed settings, validated at boot.

A missing or malformed setting crashes the process on startup, not at 3am on the
first request that needs it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Never delivered, on any surface. A module constant rather than an inline
# default so tests and the cleanup tooling can import the same list.
DEFAULT_BLOCK_TERMS: tuple[str, ...] = (
    "israel",
    "israels",
    "israeli",
    "israelis",
    "idf",
    "gaza",
    "gazan",
    "gazans",
    "jerusalem",
    "tel aviv",
    "west bank",
    "knesset",
    "netanyahu",
    "mossad",
    "shin bet",
    "zionist",
    "zionism",
    "hamas",
    "hezbollah",
    "haaretz",
    "unit 8200",
    "nso group",
)

# Publishers we do not carry. Distinct from `sites.opt_out_at`, which records
# that a PUBLISHER asked to be removed (invariant #3) -- this records that the
# OPERATOR banned them. Conflating the two would put words in a publisher's
# mouth and make "why is this site off?" unanswerable.
#
# Matched on the registrable domain, subdomains included.
DEFAULT_BLOCK_SITES: tuple[str, ...] = ("bbc.co.uk",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TT_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    env: Literal["local", "staging", "prod"] = "local"
    log_level: str = "INFO"

    # --- storage --------------------------------------------------------
    database_url: str = "postgresql+asyncpg://postgres:dev@localhost:5432/techtrend"
    database_pool_size: int = 10
    redis_url: str = "redis://localhost:6379/0"
    s3_bucket: str = "techtrend-local"
    s3_endpoint: str | None = None  # set for MinIO locally
    s3_access_key: str = "dev"  # MinIO only; ignored when endpoint is unset
    s3_secret_key: str = "devdevdev"  # noqa: S105 - local MinIO default; prod forbids s3_endpoint

    # --- crawler --------------------------------------------------------
    user_agent: str = "TechTrendBot/1.0 (+https://techtrend.example/bot; bot@techtrend.example)"
    # Hard ceiling. Invariant: one or two connections per site, never more.
    # An over-eager TT_PER_HOST_CONCURRENCY=32 is a *startup failure*, not a
    # publisher complaint.
    per_host_concurrency: int = Field(default=2, ge=1, le=2)
    fetch_timeout_s: float = 20.0
    respect_robots: bool = True

    # --- embeddings ------------------------------------------------------
    # SEMI-PERMANENT: changing the model is a corpus-wide re-embed.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_fake: bool = False  # deterministic vectors; tests set this

    # --- ai -------------------------------------------------------------
    # Not TT_-prefixed: same var the Anthropic SDK reads from the process
    # env. Loading it here too makes `.env` sufficient in local dev.
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    ai_model: str = "claude-opus-5"
    # Distill is expansion, not judgment, and the user is WAITING (~2s budget).
    # Haiku is fast and cheap and good at it; judging quality stays on ai_model.
    ai_distill_model: str = "claude-haiku-4-5"
    # Summarising is rewriting, not judgment, and it runs once per posted
    # story. Haiku is fast, cheap and good at it -- measured 2026-08-20 at
    # ~830 input / ~110 output tokens per article, about $1.20/month at 28/day.
    ai_summary_model: str = "claude-haiku-4-5"
    # Answering is reasoning, not rewriting: the reader is asking something the
    # article does not state outright, and the failure we care about -- a
    # confident answer from memory rather than from the text -- is what a
    # weaker model does more often. ~$0.012/question, ~$7/month at 20/day.
    ai_answer_model: str = "claude-opus-5"
    ai_answer_effort: Effort = "medium"
    ai_judge_effort: Effort = "medium"
    ai_distill_effort: Effort = "low"
    ai_batch_enabled: bool = True
    ai_interactive_priority_max: int = 50
    ai_fake: bool = False

    # --- quality knobs (swept by the harnesses, not guessed) -------------
    # Calibrated 2026-08-07 on the first live corpus: real cross-outlet
    # duplicates score title_j 0.17-0.50, entity_j 0.29-0.47; near-miss
    # different-event pairs (cos ~0.97 listicles) score title_j < 0.1.
    cluster_cos_min: float = 0.86
    cluster_title_min: float = 0.15
    cluster_entity_min: float = 0.20
    novelty_window_days: int = 30
    group_window_hours: int = 72
    match_vector_topk: int = 200

    # --- delivery -------------------------------------------------------
    dashboard_max_cards: int = 12
    cap_per_topic: int = 3
    cap_per_source: int = 3
    exploration_slots: int = 1
    breaking_alerts_per_day: int = 2
    # NOTE: there is deliberately no `dashboard_min_cards`. Invariant #10 --
    # never pad a short day -- is enforced by the absence of a floor.

    # --- global content block --------------------------------------------
    # A hard, corpus-wide gate: any story whose title, publisher description or
    # extracted entities hit one of these terms is dropped at match time and
    # again at notify time. This is NOT a topic `exclude` -- those are per
    # topic, and a topic added tomorrow would not inherit them. This one
    # applies to every topic, every feed and every channel, which is the point.
    #
    # Word-boundary matched on normalised text, so "israel" does not match
    # "israeli" -- variants are listed explicitly. Override wholesale in .env
    # with TT_BLOCK_TERMS='["..."]'; an empty list disables the gate.
    block_terms: list[str] = Field(default_factory=lambda: list(DEFAULT_BLOCK_TERMS))
    # Banned publishers. Gates collection at the sweep, matching, and posting.
    # Removing a domain here is not enough to bring a site back -- its seed
    # entry has to exist too. Override with TT_BLOCKED_SITES='["..."]'.
    blocked_sites: list[str] = Field(default_factory=lambda: list(DEFAULT_BLOCK_SITES))

    # --- slack delivery --------------------------------------------------
    # Bot token (xoxb-, scope chat:write) + the channel it posts into. Both
    # unset = the notify stage is inert and nothing is ever enqueued.
    slack_bot_token: SecretStr | None = None
    slack_channel: str | None = None  # "#tech-updates" or a channel id
    # Which topics reach Slack. EMPTY MEANS EVERY TOPIC -- narrow it in .env
    # (TT_SLACK_TOPIC_IDS='[1,3,13]'), widen it by removing the var.
    slack_topic_ids: list[int] = Field(default_factory=list)
    # Calibrated 2026-08-20 against the live corpus: on the AI topics, >=0.5
    # yields ~50 stories/day, >=0.6 ~28/day (about one an hour), >=0.7 ~4/day.
    slack_match_floor: float = Field(default=0.6, ge=0.0, le=1.0)
    # Per-topic overrides, because one floor cannot serve topics with different
    # score distributions. Job listings score lower than news stories -- the
    # boilerplate board description gives the matcher little to work with -- so
    # 0.6 yields one qualifying listing every ten days, while the same floor on
    # AI models & labs already yields 27/day. Keyed by topic id.
    slack_topic_floors: dict[int, float] = Field(default_factory=dict)
    # A backlog is not news. Nothing older than this is ever announced.
    slack_max_age_hours: float = 24.0
    slack_timeout_s: float = 15.0
    # Post a plain-language summary as a threaded reply under each card.
    # Costs one Haiku call per story; set false to stop spending entirely.
    slack_summaries: bool = True
    # Extraction is imperfect. Below this, the "article" is usually a paywall
    # notice or a nav menu -- not worth an API call, and worse if summarised.
    slack_summary_min_chars: int = 600
    # Socket Mode app-level token (xapp-, scope connections:write). Without it
    # the Q&A listener will not start -- there is no public HTTPS endpoint on
    # this host for Slack's Events API to reach, so the outbound WebSocket is
    # the only way in.
    slack_app_token: SecretStr | None = None
    # A question can pull in the whole article; cap what we send.
    slack_qa_max_body_chars: int = 12000
    slack_qa_max_thread_msgs: int = 20

    # --- worker ---------------------------------------------------------
    worker_concurrency: int = 8
    worker_poll_idle_s: float = 0.5
    job_lease_minutes: int = 15
    # How often the worker enqueues its own maintenance job (reap stale locks,
    # purge done rows). Nothing else enqueues it -- see cli._sweep_maintenance.
    maintenance_interval_s: int = 300

    # --- auth -----------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-secret")
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 90 * 24 * 3600

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; swap asyncpg for psycopg."""
        return self.database_url.replace("+asyncpg", "+psycopg")


def site_blocked(domain: str | None, blocked: list[str] | tuple[str, ...]) -> str | None:
    """The banned domain this site falls under, or None.

    Suffix-aware, so banning "bbc.co.uk" also bans "news.bbc.co.uk" -- a ban a
    subdomain walks around is not a ban. Returns the matched entry rather than
    a bool so the skip can say which rule fired.
    """
    if not domain:
        return None
    d = domain.strip().lower().removeprefix("www.")
    for b in blocked:
        bb = b.strip().lower().removeprefix("www.")
        if bb and (d == bb or d.endswith(f".{bb}")):
            return bb
    return None


@lru_cache
def settings() -> Settings:
    return Settings()


def check_production_invariants(s: Settings) -> None:
    """Fail closed. A misconfigured container never takes traffic."""
    if s.env != "prod":
        return
    if not s.respect_robots:
        raise RuntimeError("robots.txt cannot be disabled in production")
    if s.jwt_secret.get_secret_value() == "dev-secret":
        raise RuntimeError("refusing to boot prod with the dev JWT secret")
    if s.s3_endpoint is not None:
        raise RuntimeError("prod must use real S3, not a custom endpoint")
    if s.ai_fake:
        raise RuntimeError("refusing to boot prod with the fake AI client")
