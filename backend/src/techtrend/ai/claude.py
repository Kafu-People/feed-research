"""The real Claude client.

Two call sites exist in the whole system: judge (one per *story*, the dominant
AI cost) and distill (one per topic created, on the onboarding critical path).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import anthropic

from techtrend.ai.schemas import JudgeResult, TopicDraft
from techtrend.platform.config import settings
from techtrend.platform.telemetry import AI_TOKENS, log

MODEL = "claude-opus-5"

_PROMPTS = Path(__file__).parent / "prompts"
# Loaded once at import. NEVER an f-string: interpolating a date, a story id or
# a build hash into the system prompt silently kills prompt caching.
JUDGE_SYSTEM = (_PROMPTS / "judge.md").read_text()
DISTILL_SYSTEM = (_PROMPTS / "distill.md").read_text()


class Refused(Exception):
    """Safety classifiers declined. A news corpus contains security stories,
    so this is not hypothetical -- handle it, never let it drop a story."""

    def __init__(self, category: str | None) -> None:
        super().__init__(f"refused: {category}")
        self.category = category


class ClaudeClient:
    def __init__(self) -> None:
        # Credentials resolve from the environment (ANTHROPIC_API_KEY, or an
        # `ant auth login` profile). Never hardcode a key. Settings also loads
        # ANTHROPIC_API_KEY from .env so local dev works without an export.
        key = settings().anthropic_api_key
        self._c = anthropic.AsyncAnthropic(
            api_key=key.get_secret_value() if key else None, max_retries=3, timeout=120.0
        )

    async def judge(self, title: str, body: str, **kw: object) -> JudgeResult:
        s = settings()
        resp = await self._c.messages.parse(
            model=s.ai_model,
            # Headroom for THINKING, not for output: thinking is on by default
            # on claude-opus-5 and max_tokens caps thinking + response text.
            max_tokens=16000,
            output_config={"effort": s.ai_judge_effort},
            system=[
                {
                    "type": "text",
                    "text": JUDGE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _render_judge(title, body, kw)}],
            output_format=JudgeResult,
        )
        # Check stop_reason BEFORE reading content: a refusal is HTTP 200 with
        # an empty or partial content array.
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("judge", resp.usage, model=s.ai_model)
        return cast("JudgeResult", resp.parsed_output)

    async def distill(self, sentence: str) -> TopicDraft:
        s = settings()
        resp = await self._c.messages.parse(
            model=s.ai_distill_model,
            max_tokens=8000,
            system=[
                {
                    "type": "text",
                    "text": DISTILL_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": sentence}],
            output_format=TopicDraft,
        )
        if resp.stop_reason == "refusal":
            raise Refused(None)
        _observe("distill", resp.usage, model=s.ai_distill_model)
        return cast("TopicDraft", resp.parsed_output)


def _render_judge(title: str, body: str, kw: dict[str, object]) -> str:
    prior = kw.get("prior_facts") or []
    return (
        f"<story>\n<headline>{title}</headline>\n<sources>\n{body}\n</sources>\n</story>\n"
        f"<prior_coverage_30d>\n{prior}\n</prior_coverage_30d>"
    )


def _observe(stage: str, usage: object, *, model: str = MODEL) -> None:
    for field in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = getattr(usage, field, 0) or 0
        AI_TOKENS.labels(stage=stage, kind=field).inc(value)
    # If cache_read stays flat at zero across repeated calls, a silent cache
    # invalidator has been introduced -- nothing breaks, the bill doubles.
    log.info(
        "ai.call",
        stage=stage,
        model=model,
        effort=settings().ai_judge_effort,
        cache_read=getattr(usage, "cache_read_input_tokens", 0),
    )
