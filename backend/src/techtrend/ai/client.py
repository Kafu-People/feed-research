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

MODEL = "claude-opus-5"


class AIClient(Protocol):
    async def judge(self, title: str, body: str, **kw: object) -> JudgeResult: ...
    async def distill(self, sentence: str) -> TopicDraft: ...


@lru_cache
def client() -> AIClient:
    s = settings()
    if s.ai_fake:
        return FakeAIClient()
    from techtrend.ai.claude import ClaudeClient  # imported lazily: optional dep

    return ClaudeClient()
