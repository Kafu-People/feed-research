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
            # Headroom for THINKING, not just the reply: thinking is on by
            # default on claude-opus-5 and max_tokens caps thinking + text.
            max_tokens=8000,
            output_config={"effort": s.ai_answer_effort},
            system=[
                {
                    "type": "text",
                    "text": ANSWER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
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
        _observe("answer", resp.usage, model=s.ai_answer_model)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or "I could not produce an answer for that one."

    async def summarize(self, title: str, body: str) -> str | None:
        """Plain-language summary for a chat channel. None when unsummarisable.

        No `output_config.effort` and no thinking: both error on Haiku 4.5, and
        a 2-sentence rewrite needs neither. No `cache_control` either -- this
        system prompt is well under Haiku 4.5's 4096-token cache minimum, so a
        breakpoint here would never produce a hit.
        """
        s = settings()
        resp = await self._c.messages.create(
            model=s.ai_summary_model,
            max_tokens=400,
            system=[{"type": "text", "text": SUMMARIZE_SYSTEM}],
            messages=[{"role": "user", "content": f"{title}\n\n{body}"}],
        )
        # Check stop_reason BEFORE reading content: a refusal is HTTP 200 with
        # an empty or partial content array.
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("summarize", resp.usage, model=s.ai_summary_model)

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
            # Headroom for thinking as well as output: on claude-opus-5
            # max_tokens caps both, and deciding what mattered is the thinking.
            max_tokens=8000,
            output_config={"effort": s.ai_digest_effort},
            system=[{"type": "text", "text": DIGEST_SYSTEM}],
            messages=[{"role": "user", "content": headlines}],
        )
        if resp.stop_reason == "refusal":
            cat = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise Refused(cat)
        _observe("digest", resp.usage, model=s.ai_digest_model)
        return "".join(b.text for b in resp.content if b.type == "text").strip()

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
