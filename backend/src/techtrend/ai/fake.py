"""Deterministic stand-in so most of the codebase needs no API key.

TT_AI_FAKE=true swaps this in. Contributors touching collection, extraction,
grouping, matching, ranking, the API or the clients never need a key.
"""

from __future__ import annotations

import re

from techtrend.ai.schemas import Fact, JudgeResult, TopicDraft

_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "about",
    "for",
    "with",
    "of",
    "in",
    "on",
    "to",
    "i",
    "want",
    "follow",
    "news",
    "especially",
    "my",
    "me",
}


class FakeAIClient:
    async def judge(self, title: str, body: str, **_: object) -> JudgeResult:
        nums = re.findall(r"\d[\d,.]*", f"{title} {body}")
        return JudgeResult(
            summary=f"{title.rstrip('.')}. Reported across the covering outlets.",
            story_type="original_reporting",
            facts=[Fact(kind="number", value=n) for n in nums[:5]],
            novelty=0.5,
            novelty_rationale="fake client: fixed mid-range novelty",
        )

    async def distill(self, sentence: str) -> TopicDraft:
        words = [w for w in re.findall(r"[\w-]+", sentence.lower()) if w not in _STOP]
        must = [w for w in words if len(w) > 2][:6] or ["news"]
        caps = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", sentence)
        return TopicDraft(
            title=sentence[:60].strip().rstrip(".") or "Untitled topic",
            must=must,
            should=words[6:10],
            entities=list(dict.fromkeys(caps))[:5],
            exclude=[],
            ambiguity=None,
        )
