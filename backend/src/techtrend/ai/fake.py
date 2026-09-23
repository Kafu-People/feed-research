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

    async def answer(self, question: str, title: str, body: str, _thread: str) -> str:
        if question.strip().endswith("?") and question.lower().split()[:1] == ["when"]:
            return "The article doesn't say."
        return f"About {title.rstrip('.')}: {question.strip().rstrip('?')} -- per the article, yes."

    async def summarize(self, title: str, body: str) -> str | None:
        if len(body) < 200:
            return None  # mirrors the real client's SKIP on thin extraction
        return f"{title.rstrip('.')}. In plain terms, this is what the coverage says."

    async def summarize_batch(self, items: list[tuple[int, str, str]]) -> dict[int, str | None]:
        """Same rule as `summarize`, applied per item. Deterministic, offline,
        and it returns the SHAPE the batch path has to handle: a mapping that
        may be missing keys and may hold None."""
        return {sid: await self.summarize(title, body) for sid, title, body in items}

    async def collect_batch(self, batch_id: str) -> dict[int, str | None]:
        """Nothing is ever left pending offline."""
        return {}

    async def batch_ended(self, batch_id: str) -> bool:
        return True

    async def read_batch(self, batch_id: str) -> dict[int, str | None]:
        return {}

    async def digest(self, headlines: str) -> str:
        n = len([ln for ln in headlines.splitlines() if ln.strip().startswith(("1", "2", "3"))])
        return f"A steady day across the feed.\n\n\u2022 `{n}` stories carried, mostly routine."

    async def weekly(self, headlines: str) -> str:
        n = len([ln for ln in headlines.splitlines() if ln.strip()])
        return (
            "A steady week across the feed.\n\nTHE WEEK\n\n"
            f"\u2022 `{n}` stories carried, mostly routine.\n\n"
            "WHAT IT POINTS TO\n\n\u2022 Probably more of the same. Wrong if volume moves."
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
