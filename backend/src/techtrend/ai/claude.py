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
SUMMARIZE_SYSTEM = (_PROMPTS / "summarize.md").read_text()
ANSWER_SYSTEM = (_PROMPTS / "answer.md").read_text()
DIGEST_SYSTEM = (_PROMPTS / "digest.md").read_text()


class Refused(Exception):
    """Safety classifiers declined. A news corpus contains security stories,
    so this is not hypothetical -- handle it, never let it drop a story."""

    def __init__(self, category: str | None) -> None:
        super().__init__(f"refused: {category}")
        self.category = category


def _is_haiku(model: str) -> bool:
    return "haiku" in model


def _effort_kwargs(model: str, effort: str) -> dict[str, object]:
    """`output_config.effort` is a 400 on Haiku 4.5 and required on Opus 5.

    Opus 5 has extended thinking ON by default. Sending no effort setting does
    not disable it -- it just leaves it uncontrolled, which for a three-sentence
    rewrite means paying for reasoning tokens that change nothing.
    """
    return {} if _is_haiku(model) else {"output_config": {"effort": effort}}


def _max_tokens(model: str, *, plain: int, thinking: int) -> int:
    """Haiku writes straight into the response; a thinking model does not.

    On Opus, max_tokens caps thinking AND output TOGETHER, so a cap sized for
    the answer alone gets swallowed by reasoning and returns an empty content
    array -- which reads to the caller as a model that declined. Hence two
    numbers: what the text needs, and what the text plus thinking needs.
    """
    return plain if _is_haiku(model) else thinking


# Anthropic will not cache a prefix below this many tokens: 4096 on Haiku 4.5,
# 1024 on Sonnet and Opus. Every prompt in ai/prompts/ is smaller than BOTH
# (judge 284, answer 693, summarize 998, digest 1324), so a cache_control
# breakpoint on any of them is a no-op that reads like an optimisation. They
# are deliberately absent below. Re-measure before adding one back.
HAIKU_CACHE_MIN_TOKENS = 4096


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
            max_tokens=_max_tokens(s.ai_model, plain=4000, thinking=16000),
            system=[{"type": "text", "text": JUDGE_SYSTEM}],
            messages=[{"role": "user", "content": _render_judge(title, body, kw)}],
            output_format=JudgeResult,
            **_effort_kwargs(s.ai_model, s.ai_judge_effort),
        )
        # Check stop_reason BEFORE reading content: a refusal is HTTP 200 with
        # an empty or partial content array.
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("judge", resp.usage, model=s.ai_model, effort=s.ai_judge_effort)
        return cast("JudgeResult", resp.parsed_output)

    async def answer(self, question: str, title: str, body: str, thread: str) -> str:
        """Answer a question about one article, grounded in its text.

        Opus because a question is reasoning, not rewriting: the reader is
        asking something the article does not state outright, and the failure
        mode we care about -- answering confidently from memory instead of from
        the text -- is exactly what a weaker model does more often.
        """
        s = settings()
        resp = await self._c.messages.create(
            model=s.ai_answer_model,
            max_tokens=_max_tokens(s.ai_answer_model, plain=1500, thinking=8000),
            system=[{"type": "text", "text": ANSWER_SYSTEM}],
            **_effort_kwargs(s.ai_answer_model, s.ai_answer_effort),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"<article>\n<headline>{title}</headline>\n{body}\n</article>\n"
                        f"<thread_so_far>\n{thread}\n</thread_so_far>\n"
                        f"<question>\n{question}\n</question>"
                    ),
                }
            ],
        )
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("answer", resp.usage, model=s.ai_answer_model, effort=s.ai_answer_effort)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or "I could not produce an answer for that one."

    async def summarize(self, title: str, body: str) -> str | None:
        """Plain-language summary for a chat channel. None when unsummarisable.

        The model is configurable and the two families need different calls --
        see `_effort_kwargs` and `_max_tokens` for why.
        """
        s = settings()
        resp = await self._c.messages.create(
            model=s.ai_summary_model,
            max_tokens=_max_tokens(s.ai_summary_model, plain=400, thinking=3000),
            system=[{"type": "text", "text": SUMMARIZE_SYSTEM}],
            messages=[{"role": "user", "content": f"{title}\n\n{body}"}],
            **_effort_kwargs(s.ai_summary_model, s.ai_summary_effort),
        )
        # Check stop_reason BEFORE reading content: a refusal is HTTP 200 with
        # an empty or partial content array.
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("summarize", resp.usage, model=s.ai_summary_model, effort=s.ai_summary_effort)

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        # The prompt's own escape hatch for boilerplate that survived extraction.
        if not text or text.strip().rstrip(".") == "SKIP":
            return None
        return text

    async def digest(self, headlines: str) -> str:
        """One roundup of the day from the day's headlines.

        Runs once a day, so there is no caching to win here -- a breakpoint on
        a system prompt seen once every 24 hours never hits a live cache.
        """
        s = settings()
        resp = await self._c.messages.create(
            model=s.ai_digest_model,
            max_tokens=_max_tokens(s.ai_digest_model, plain=2000, thinking=8000),
            system=[{"type": "text", "text": DIGEST_SYSTEM}],
            **_effort_kwargs(s.ai_digest_model, s.ai_digest_effort),
            messages=[{"role": "user", "content": headlines}],
        )
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("digest", resp.usage, model=s.ai_digest_model, effort=s.ai_digest_effort)
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def distill(self, sentence: str) -> TopicDraft:
        s = settings()
        resp = await self._c.messages.parse(
            model=s.ai_distill_model,
            max_tokens=_max_tokens(s.ai_distill_model, plain=1000, thinking=8000),
            system=[{"type": "text", "text": DISTILL_SYSTEM}],
            messages=[{"role": "user", "content": sentence}],
            output_format=TopicDraft,
            **_effort_kwargs(s.ai_distill_model, s.ai_distill_effort),
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


def _observe(stage: str, usage: object, *, model: str = MODEL, effort: str = "-") -> None:
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
        # Was hardcoded to ai_judge_effort, so every stage logged the judge's
        # setting -- which reads as a bug in whichever stage you are debugging.
        effort=effort,
        cache_read=getattr(usage, "cache_read_input_tokens", 0),
    )
