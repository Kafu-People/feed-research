"""Gemini as the writing model for the channel, keeping Claude for judging.

The operator's call: the briefs read better than the summaries, and both use
the same house style, so the difference is the model. This routes the writing
work -- summaries, the digest, the weekly roundup, Q&A answers -- to Gemini.

`judge` and `distill` stay on Claude and are delegated, not reimplemented.
They return typed objects through `messages.parse()`, and porting structured
output to another vendor's JSON-schema dialect is a different job with a
different failure mode. Judging is not even running today.

NO grounding on any of this. These calls summarise text the crawler already
stored, so search would be both dearer and wrong: the summary has to describe
THAT article, not the web's view of its subject.
"""

from __future__ import annotations

import asyncio

from techtrend.ai import gemini
from techtrend.ai.claude import (
    ANSWER_SYSTEM,
    DIGEST_SYSTEM,
    SUMMARIZE_SYSTEM,
    WEEKLY_SYSTEM,
    ClaudeClient,
)
from techtrend.ai.schemas import JudgeResult, TopicDraft
from techtrend.platform.config import settings
from techtrend.platform.telemetry import AI_TOKENS, log


class GeminiClient:
    """Satisfies the same protocol as ClaudeClient."""

    def __init__(self) -> None:
        # Built lazily and kept, so a run that never judges never constructs
        # an Anthropic client or needs its key.
        self._claude: ClaudeClient | None = None

    def _fallback(self) -> ClaudeClient:
        if self._claude is None:
            self._claude = ClaudeClient()
        return self._claude

    # ---- delegated: typed output, still Claude's job --------------------

    async def judge(self, title: str, body: str, **kw: object) -> JudgeResult:
        return await self._fallback().judge(title, body, **kw)

    async def distill(self, sentence: str) -> TopicDraft:
        return await self._fallback().distill(sentence)

    # ---- written by Gemini ----------------------------------------------

    async def summarize(self, title: str, body: str) -> str | None:
        text = await self._write("summarize", SUMMARIZE_SYSTEM, f"{title}\n\n{body}")
        # The prompt's own escape hatch for boilerplate that survived
        # extraction, honoured identically to the Claude path.
        if not text or text.rstrip(".") == "SKIP":
            return None
        return text

    async def summarize_batch(self, items: list[tuple[int, str, str]]) -> dict[int, str | None]:
        """Concurrently, not batched: Gemini has no batch endpoint here.

        The Anthropic path buys a 50% discount by going asynchronous, which
        cost a whole collector, a retry chain and a `summary_attempts` column.
        These calls are cheap enough per token that paying full price for a
        synchronous answer is the better trade -- and it removes the deferred
        path entirely, so a summary either exists or is retried next hour.
        """
        sem = asyncio.Semaphore(settings().gemini_concurrency)

        async def one(sid: int, title: str, body: str) -> tuple[int, str | None]:
            async with sem:
                try:
                    return sid, await self.summarize(title, body)
                except gemini.Transient:
                    raise
                except Exception:  # noqa: BLE001 - one story, not the batch
                    log.warning("gemini.summary_failed", story_id=sid)
                    return sid, None

        done = await asyncio.gather(*(one(*it) for it in items))
        return dict(done)

    async def answer(self, question: str, title: str, body: str, thread: str) -> str:
        user = (
            f"<article>\n<headline>{title}</headline>\n{body}\n</article>\n"
            f"<thread>\n{thread}\n</thread>\n<question>\n{question}\n</question>"
        )
        return await self._write("answer", ANSWER_SYSTEM, user)

    async def digest(self, headlines: str) -> str:
        return await self._write("digest", DIGEST_SYSTEM, headlines)

    async def weekly(self, headlines: str) -> str:
        return await self._write("weekly", WEEKLY_SYSTEM, headlines)

    # ---- batch shims ------------------------------------------------------
    # Nothing is ever pending: `summarize_batch` returns finished work, so the
    # collector path in the summarise stage simply never fires.

    async def collect_batch(self, batch_id: str) -> dict[int, str | None]:
        return {}

    async def batch_ended(self, batch_id: str) -> bool:
        return True

    async def read_batch(self, batch_id: str) -> dict[int, str | None]:
        return {}

    async def _write(self, stage: str, system: str, user: str) -> str:
        model = settings().gemini_write_model
        text, tin, tout = await gemini.write(system, user, model=model)
        AI_TOKENS.labels(stage=stage, kind="input_tokens").inc(tin)
        AI_TOKENS.labels(stage=stage, kind="output_tokens").inc(tout)
        log.info("ai.call", stage=stage, model=model, vendor="gemini")
        return text.strip()
