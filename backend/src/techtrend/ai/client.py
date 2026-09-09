"""The only place Claude is called.

`import-linter` forbids api/ and personal/ from importing this module directly,
so a request handler cannot make a judging call: AI spend scales with
stories/day, not with users.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from techtrend.ai.fake import FakeAIClient
from techtrend.ai.schemas import JudgeResult, TopicDraft
from techtrend.platform.config import settings


class AIClient(Protocol):
    async def judge(self, title: str, body: str, **kw: object) -> JudgeResult: ...
    async def distill(self, sentence: str) -> TopicDraft: ...
    async def summarize(self, title: str, body: str) -> str | None: ...
    async def summarize_batch(self, items: list[tuple[int, str, str]]) -> dict[int, str | None]: ...
    async def collect_batch(self, batch_id: str) -> dict[int, str | None]: ...
    async def batch_ended(self, batch_id: str) -> bool: ...
    async def read_batch(self, batch_id: str) -> dict[int, str | None]: ...
    async def answer(self, question: str, title: str, body: str, thread: str) -> str: ...
    async def digest(self, headlines: str) -> str: ...
    async def weekly(self, headlines: str) -> str: ...


@lru_cache
def client() -> AIClient:
    s = settings()
    if s.ai_fake:
        return FakeAIClient()
    from techtrend.ai.claude import ClaudeClient  # imported lazily: optional dep

    return ClaudeClient()
