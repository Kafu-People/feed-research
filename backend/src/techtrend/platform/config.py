"""Typed settings, validated at boot.

A missing or malformed setting crashes the process on startup, not at 3am on the
first request that needs it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    # Trump, banned 2026-09-01. "trumps" carries the possessive, because
    # normalise_term strips the apostrophe from "Trump's". Checked against
    # 15,275 live articles first: all 35 "trumps" hits were the name, none
    # were the verb ("speed trumps accuracy"), so the term is safe here.
    "trump",
    "trumps",
    "trumpism",
    "maga",
    "truth social",
    "mar a lago",
    # South Korea, banned 2026-09-07. Each term checked against 19,187 live
    # articles first.
    #
    # "south korean" is listed separately because the gate matches on word
    # boundaries: "south korea" does NOT hit "South Korean", the trailing "n"
    # defeats the lookahead.
    #
    # Bare "korea"/"korean" are deliberately NOT here. They would match "North
    # Korean", a different country, and the 14 articles that hit are Lazarus
    # and IT-worker security reporting the Cybersecurity topic wants. The cost
    # is real: ~14 South Korea articles say only "Korean" (a lunar orbiter, the
    # Kospi) and survive. Under-blocking was chosen over deleting another
    # country's security coverage, which no later edit can bring back.
    #
    # "lg" is safe on word boundaries -- all 68 hits were the company, none
    # were an abbreviation. "seoul" catches an Android game with the city in
    # its title; three articles, judged acceptable.
    "south korea",
    "south korean",
    "south koreans",
    "seoul",
    "kospi",
    "sk hynix",
    "hynix",
    "lg",
)

# Publishers we do not carry. Distinct from `sites.opt_out_at`, which records
# that a PUBLISHER asked to be removed (invariant #3) -- this records that the
# OPERATOR banned them. Conflating the two would put words in a publisher's
# mouth and make "why is this site off?" unanswerable.
#
# Matched on the registrable domain, subdomains included.
DEFAULT_BLOCK_SITES: tuple[str, ...] = ("bbc.co.uk",)

# Every per-stage model setting, in one place. A module constant, not a class
# attribute: a leading-underscore attribute on a pydantic model becomes a
# private attr that the class itself cannot read back, so the test that checks
# this list is complete could not import it. Tests assert it covers every
# `ai_*_model` field, which is what stops a stage added later from being
# silently unguarded.
AI_MODEL_FIELDS: tuple[str, ...] = (
    "ai_model",
    "ai_distill_model",
    "ai_summary_model",
    "ai_answer_model",
    "ai_weekly_model",
    "ai_digest_model",
)


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
    # Every stage runs on Haiku 4.5 by user decision (2026-09-02). Each model
    # setting is still separate, so one stage can be promoted without moving
    # the rest -- `_effort_kwargs` and `_max_tokens` in ai/claude.py absorb
    # the call-shape differences between the families either way.
    ai_model: str = "claude-haiku-4-5"
    # Distill is expansion, not judgment, and the user is WAITING (~2s budget).
    # Haiku is fast and cheap and good at it; judging quality stays on ai_model.
    ai_distill_model: str = "claude-haiku-4-5"
    # Summarising runs once per posted story, and it is the most-read output
    # the system produces -- every reader in the channel sees it.
    # Measured 2026-09-01 on live articles against the student-readability
    # rules in summarize.md: Opus followed them best (mean sentence 17.7 words
    # vs Haiku's 24.1) but cost $14.66/month against Haiku's $2.13 at 28
    # summaries/day. Haiku chosen deliberately -- the gap is real but not worth
    # 7x, and as of 2026-09-07 the user has settled it: summaries are Haiku,
    # full stop. `_require_haiku_summaries_and_no_opus` below makes anything
    # else fail at boot, so this is no longer a one-line switch.
    ai_summary_model: str = "claude-haiku-4-5"
    # Rewriting, not reasoning: the thinking budget buys nothing here, and on
    # Opus it is on by default until told otherwise.
    ai_summary_effort: Effort = "low"
    # Answering is reasoning, not rewriting: the reader is asking something the
    # article does not state outright, and the failure we care about -- a
    # confident answer from memory rather than from the text -- is what a
    # weaker model does more often. ~$0.012/question, ~$7/month at 20/day.
    ai_answer_model: str = "claude-haiku-4-5"
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
    # Posting cadence. 0 posts a card the moment its story matches -- the
    # original behaviour. Above 0, a matched story's notify job is delayed to
    # the next interval boundary, so an interval's cards land together.
    #
    # Two reasons, and the second is the expensive one. It is quieter in the
    # channel, and it gives the summariser a BATCH to work on: an hour's
    # stories go to the model as one Message Batches submission at 50% off,
    # instead of N live calls at full price. Measured 2026-09-08 over 14 days:
    # 2.2 posts in an average active hour, so an hour is the shortest interval
    # that batches anything at all -- 45% of active hours carry exactly one.
    slack_post_interval_hours: float = 1.0
    # Summaries through the Message Batches API rather than one live call per
    # story. Asynchronous: the card posts on the hour, the summary threads
    # under it when the batch returns (minutes, not hours, at this size).
    # False restores the inline call, which is what the notify stage does when
    # it sees this off.
    ai_summary_batch: bool = True
    # How the channel is written to.
    #
    #   "cards"  -- one message per story, summary threaded under it. Each
    #               story gets its own thread, which is what the Q&A listener
    #               answers in and where a source-count follow-up lands.
    #   "hourly" -- ONE message an hour carrying every story that hour matched,
    #               each with its link and its summary inline. Chosen by the
    #               operator 2026-09-08: 2.2 stories an hour was producing ~4.4
    #               messages an hour in cards mode, with each summary detached
    #               from the headline it belonged to.
    #
    # "hourly" costs the per-story thread, and with it the Q&A listener's only
    # place to answer and the follow-up's only place to land. That is the
    # trade, stated here so it is not rediscovered as a bug.
    slack_delivery_mode: Literal["cards", "hourly"] = "hourly"
    # Ceiling on one report. A quiet hour posts what it has; a burst hour is
    # trimmed to the highest-scoring, because a Slack message has a block limit
    # and a reader has a scroll limit.
    hourly_max_stories: int = 25
    # How long after the interval boundary the report is assembled. Matching
    # for the stories that arrived at :59 has to finish first; at 17:00 on
    # 2026-09-08 it had not, and the hour reported three stories with nothing
    # under them. Clamped to half the interval so a short interval cannot
    # schedule its report into the next one.
    hourly_offset_s: float = 240.0

    # --- the daily brief (Gemini + Google Search grounding) ---------------
    # A second, separate surface: the crawled corpus says what the press
    # published, the brief says what people actually posted. Inert unless both
    # the key and the channel are set, the same rule the Slack card path uses
    # -- a key with no channel researches into the void.
    #
    # Read as GEMINI_API_KEY too, because that is the name Google's own
    # libraries and docs use and an operator will set that one by reflex.
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    # gemini-2.5-* returns 404 for new projects as of 2026-09-22; Google's own
    # error names these as the replacements.
    gemini_model: str = "gemini-3.6-flash"
    gemini_timeout_s: float = 180.0
    # Where briefs go. Deliberately NOT slack_channel: a research brief is a
    # different thing from the hourly report and should not compete with it.
    slack_brief_channel: str | None = None
    # Local hour (digest_timezone) at which the day's briefs run.
    brief_hour: int = Field(default=8, ge=0, le=23)
    # A hard ceiling on grounded searches per day. Grounding is billed per
    # search the model chooses to run -- and the model chooses, not us, so a
    # prompt that provokes ten searches costs ten. This is the stop on a bill
    # that would otherwise be shaped by the model's judgement.
    brief_max_per_day: int = 25
    # How long the summarise job waits on its own batch before handing the
    # batch id to a follow-up job. Well inside `job_lease_minutes` (15) so the
    # lease cannot expire under a poll that is still running.
    # A SHORT in-job wait, because the queue is the better place to wait.
    # Measured on three consecutive ten-request batches: 2 minutes, 8 minutes,
    # 40 minutes. No in-job wait is both cheap and sufficient, so this covers
    # only the fast case and `ai_batch_max_polls` covers the rest.
    ai_batch_max_wait_s: float = 90.0
    # How many times a follow-up job re-checks a batch before giving up. At
    # ai_batch_poll_s * 6 per hop that is patience measured in hours, which
    # the 40-minute batch says is the right order.
    ai_batch_max_polls: int = 40
    ai_batch_poll_s: float = 10.0
    # Ceiling on one submission. The backlog this shipped with was 77 posts;
    # a cap keeps the first run from being unbounded.
    ai_summary_batch_max: int = 100
    # How far back the summarise stage will reach for a card that still has no
    # summary. Wider than one interval on purpose -- a batch that fails, or a
    # stage that was off, leaves work behind and this is what picks it up.
    #
    # NOT unbounded, for the reason the notify stage bounds its own age: a
    # stage switched back on must not thread a month of summaries into the
    # channel. The 78-post backlog this shipped with spanned 30 days; the
    # older 28 were done once by hand rather than by widening this.
    slack_summary_max_age_hours: float = 168.0
    # How many times a card may be sent to the summariser before it is left
    # alone. The model's own SKIP hatch fires on paywall stubs and nav menus
    # -- about a third of the first backlog -- and nothing about that is
    # retryable, so without a cap those stories would be re-submitted every
    # hour for a week and cost more than the batch discount saves.
    slack_summary_max_attempts: int = 2
    slack_timeout_s: float = 15.0
    # Post a plain-language summary as a threaded reply under each card.
    # Costs one Haiku call per story; set false to stop spending entirely.
    slack_summaries: bool = True
    # Extraction is imperfect. Below this, the "article" is usually a paywall
    # notice or a nav menu -- not worth an API call, and worse if summarised.
    slack_summary_min_chars: int = 600
    # --- daily digest ----------------------------------------------------
    # One roundup of the day's channel, posted at digest_hour local time.
    digest_enabled: bool = True
    digest_hour: int = Field(default=18, ge=0, le=23)
    # An IANA zone, not a UTC offset. Brazil dropped DST in 2019 so
    # America/Sao_Paulo is a flat UTC-3 today, but hardcoding -3 would break
    # silently if that ever changes -- and it has changed before.
    digest_timezone: str = "America/Sao_Paulo"
    # The digest reads the 24h ENDING at digest_hour, not the local calendar
    # day: a calendar day would drop everything posted after 18:00 into a gap
    # that no digest ever covers.
    digest_window_hours: float = 24.0
    # Ceiling on how many stories are handed to the model. Beyond this the
    # highest-scoring survive -- a digest of 200 headlines is not a digest.
    digest_max_stories: int = 60
    # Synthesis across the whole day, not a per-article rewrite: this is the
    # one call that has to decide what actually mattered. Once a day, so even a
    # larger model would cost well under a dollar a month -- which is an
    # argument the Opus ban settles anyway; Sonnet is the only step up left.
    # The weekly roundup and its forecast. Once a week, so even a larger model
    # is pennies -- but the forecast half is the reason to consider one.
    # Ceiling on how many stories are handed to the weekly model. A week is
    # roughly seven digests, so this is sized above digest_max_stories -- but
    # a roundup of 400 headlines is not a roundup either.
    weekly_max_stories: int = 150
    ai_weekly_model: str = "claude-haiku-4-5"
    ai_weekly_effort: Effort = "medium"
    ai_digest_model: str = "claude-haiku-4-5"
    ai_digest_effort: Effort = "medium"

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

    @model_validator(mode="after")
    def _require_haiku_summaries_and_no_opus(self) -> Settings:
        """Two standing rules, enforced at boot in EVERY environment.

        The user's decision, 2026-09-07: summaries run on Haiku and nothing
        else, and no stage anywhere runs on Opus. Both were already true by
        default -- this is what stops an env var quietly undoing them at 3am,
        which is the whole reason settings are validated at startup.

        `check_production_invariants` was the wrong home: it returns early
        outside prod, and a local run that bills Opus tokens still bills them.

        Not a Literal on each field, because the model names change faster
        than this rule does -- the rule is about a family, not an id.
        """
        for field in AI_MODEL_FIELDS:
            model = str(getattr(self, field, "") or "")
            if "opus" in model.lower():
                raise ValueError(
                    f"{field}={model!r}: Opus is banned on this project. "
                    "Every stage runs on Haiku (see ai_summary_model)."
                )
        if "haiku" not in self.ai_summary_model.lower():
            raise ValueError(
                f"ai_summary_model={self.ai_summary_model!r}: summaries are Haiku only."
            )
        return self

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
