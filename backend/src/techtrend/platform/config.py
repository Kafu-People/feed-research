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

    # --- worker ---------------------------------------------------------
    worker_concurrency: int = 8
    worker_poll_idle_s: float = 0.5
    job_lease_minutes: int = 15

    # --- auth -----------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-secret")
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 90 * 24 * 3600

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously; swap asyncpg for psycopg."""
        return self.database_url.replace("+asyncpg", "+psycopg")


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
