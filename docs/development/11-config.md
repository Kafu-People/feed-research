# 11 — Configuration

← [Shared client code](10-clients-shared.md) · [Dev README](README.md) · next → [Testing](12-testing.md)

One typed settings object, validated at boot. **A missing or malformed setting crashes the
process on startup, not at 3am on the first request that needs it.**

---

## The settings model

```python
# techtrend/platform/config.py
from functools import lru_cache
from pydantic import Field, PostgresDsn, RedisDsn, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TT_", env_file=".env", env_nested_delimiter="__", frozen=True,
    )

    env: Literal["local", "staging", "prod"] = "local"
    log_level: str = "INFO"

    # --- storage -------------------------------------------------------
    database_url: PostgresDsn
    database_pool_size: int = 10
    redis_url: RedisDsn
    s3_bucket: str
    s3_endpoint: HttpUrl | None = None          # set for MinIO locally

    # --- crawler -------------------------------------------------------
    user_agent: str = "TechTrendBot/1.0 (+https://techtrend.example/bot; bot@techtrend.example)"
    per_host_concurrency: int = Field(default=2, ge=1, le=2)   # ← hard ceiling, see below
    fetch_timeout_s: float = 20.0
    respect_robots: bool = True

    # --- ai ------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None  # None → SDK resolves from env/profile
    ai_model: str = "claude-opus-5"
    ai_judge_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_distill_effort: Literal["low", "medium", "high"] = "low"
    ai_batch_enabled: bool = True
    ai_interactive_priority_max: int = 50       # jobs at/below this skip the batch queue

    # --- quality knobs (swept by the harnesses, not guessed) ------------
    cluster_cos_min: float = 0.86
    cluster_title_min: float = 0.30
    cluster_entity_min: float = 0.50
    novelty_window_days: int = 30
    group_window_hours: int = 72
    match_vector_topk: int = 200

    # --- delivery ------------------------------------------------------
    dashboard_max_cards: int = 12
    cap_per_topic: int = 3
    cap_per_source: int = 3
    exploration_slots: int = 1
    breaking_alerts_per_day: int = 2

    # --- auth ----------------------------------------------------------
    jwt_secret: SecretStr
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 90 * 24 * 3600

@lru_cache
def settings() -> Settings:
    return Settings()
```

---

## Three things this design does deliberately

**`frozen=True`.** Settings are immutable after boot. There is no runtime mutation path, so
"why is prod behaving differently" is always answered by the environment, never by
something that reassigned a value mid-process.

**`per_host_concurrency` is bounded at 2 by the type.** [Collect](../architecture/03-collect.md)
says one or two connections per site, never more. `Field(le=2)` makes an over-eager
`TT_PER_HOST_CONCURRENCY=32` a startup failure rather than a publisher complaint. Politeness
constraints belong in the type system where they can't be tuned away under load pressure.

**Quality knobs are config, not constants.** The clustering thresholds, the novelty window
and the recall breadth are the things the harnesses in [testing](12-testing.md) sweep. Being
settings means a sweep is a matrix run, not fifteen commits — and it means a bad threshold
can be rolled back without a deploy.

Note what is *not* here: `dashboard_min_cards`. There is no floor because there is no
padding ([invariant #10](../architecture/14-invariants.md)) — the absent setting is the
enforcement.

---

## Environment variables

`TT_` prefix, `__` for nesting.

```bash
TT_ENV=prod
TT_DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/techtrend
TT_REDIS_URL=redis://cache:6379/0
TT_S3_BUCKET=techtrend-prod-articles
TT_JWT_SECRET=...
ANTHROPIC_API_KEY=...            # ← not TT_-prefixed; the SDK reads it directly
TT_AI_JUDGE_EFFORT=medium
TT_CLUSTER_COS_MIN=0.86
```

**`ANTHROPIC_API_KEY` intentionally keeps its own name.** The Anthropic SDK resolves
credentials itself (env var, then `ANTHROPIC_AUTH_TOKEN`, then an `ant auth login` profile),
and constructing `AsyncAnthropic()` with no arguments is the supported path. Renaming it
into our namespace would break the profile fallback that makes local development work
without a static key.

---

## Per-environment

| Setting | local | staging | prod |
| --- | --- | --- | --- |
| `env` | `local` | `staging` | `prod` |
| `s3_endpoint` | MinIO | AWS | AWS |
| `respect_robots` | `true` | `true` | `true` |
| `ai_batch_enabled` | `false` (fast loops) | `true` | `true` |
| `ai_judge_effort` | `low` (cheap iteration) | `medium` | `medium` |
| `database_pool_size` | 5 | 10 | 20 (API) / 8 (worker) |

`respect_robots` is `true` everywhere including local. A "convenient" local override is
exactly how a politeness rule stops being true in the code that ships.

---

## Secrets

| Secret | Local | Deployed |
| --- | --- | --- |
| `TT_JWT_SECRET` | `.env` (gitignored) | Secrets manager → env at container start |
| `ANTHROPIC_API_KEY` | `ant auth login` profile, or `.env` | Secrets manager |
| DB / S3 credentials | compose defaults | IAM role where possible; secrets manager otherwise |

Rules:

- `.env` is gitignored; `.env.example` is committed with every key and no values.
- `SecretStr` for anything sensitive — Pydantic redacts it in `repr()` and in tracebacks,
  which is the difference between a leaked key and a redacted one when an exception is
  logged.
- Never log `settings()`. `telemetry.py` logs an explicit allowlist of non-secret fields at
  boot.

---

## Boot-time validation

```python
# techtrend/cli.py
def bootstrap() -> Settings:
    s = settings()                       # pydantic raises here on anything malformed
    if s.env == "prod":
        assert s.respect_robots, "robots.txt cannot be disabled in production"
        assert s.jwt_secret.get_secret_value() != "dev-secret"
        assert s.s3_endpoint is None, "prod must use real S3"
    telemetry.init(s)
    log.info("boot", env=s.env, model=s.ai_model, stages=..., version=__version__)
    return s
```

Both processes call `bootstrap()` before serving or claiming. A misconfigured container
fails its health check and never takes traffic — a rolling deploy stops on its own rather
than replacing good instances with broken ones.
