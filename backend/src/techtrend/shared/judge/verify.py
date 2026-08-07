"""Post-AI verification. Runs on EVERY result before anything is persisted.

Invariant #7: every number in a summary must be verified against the source
-- a hallucinated percentage in one screenshot ends the product's
credibility. Invariant #2: summaries must be genuinely rewritten; we would
rather ship no summary than an infringing one.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from techtrend.ai.schemas import JudgeResult
from techtrend.platform import telemetry

NUM = re.compile(r"[-+]?\d[\d,.]*\s*(?:%|bn|billion|m|million|k|thousand|trillion|tn)?", re.I)

_SUFFIX = {
    "%": Decimal(1),
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "m": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
    "tn": Decimal(1_000_000_000_000),
    "trillion": Decimal(1_000_000_000_000),
}


def normalize(token: str) -> Decimal | None:
    """1.2bn == 1,200,000,000 == 1200000000. None for the unparseable."""
    t = token.strip().lower().replace(",", "")
    mult = Decimal(1)
    for suffix, factor in _SUFFIX.items():
        if t.endswith(suffix):
            t = t.removesuffix(suffix).strip()
            mult = factor if suffix != "%" else Decimal(1)
            break
    try:
        return Decimal(t) * mult
    except InvalidOperation:
        return None


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def verify_numbers(result: JudgeResult, source_text: str) -> JudgeResult:
    """Drop any summary sentence containing a number absent from the sources."""
    source = {n for t in NUM.findall(source_text) if (n := normalize(t)) is not None}
    kept = []
    for sentence in split_sentences(result.summary):
        nums = [n for t in NUM.findall(sentence) if (n := normalize(t)) is not None]
        if all(n in source for n in nums):
            kept.append(sentence)
    dropped = len(split_sentences(result.summary)) - len(kept)
    if dropped:
        # Monitored, not debug: a sustained rise means the prompt or the
        # model changed underneath us.
        telemetry.log.info("judge.sentences_dropped", count=dropped)
    return result.model_copy(update={"summary": " ".join(kept)})


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    words = re.findall(r"[\w']+", text.lower())
    return {tuple(words[i : i + n]) for i in range(max(0, len(words) - n + 1))}


def verify_rewritten(summary: str, source_texts: list[str], *, max_overlap: float = 0.25) -> bool:
    """Reject a summary reusing long verbatim runs from any source (inv. #2)."""
    ours = _shingles(summary)
    if not ours:
        return True
    for src in source_texts:
        theirs = _shingles(src)
        if theirs and len(ours & theirs) / len(ours) > max_overlap:
            return False
    return True
