"""Named-entity extraction, heuristic edition.

Group needs entity overlap as one of its three signals, so entity quality
gates merge quality directly. The trap is Title Case headlines ("Apple
Raises Trade-In Values For iPhone") where EVERY word is capitalised and a
naive capitalised-span heuristic returns junk that never matches across
outlets.

The rule here: a token is an entity candidate only if it is never seen
lowercased anywhere in the article's own text (true-casing). "Users" shows
up lowercase in any body; "ChatGPT" never does. Tokens with internal caps
or digits (iPhone, GPT-5, H100) qualify unconditionally. A model-based
extractor can replace this without touching callers.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z][\w.&-]*")
_CAP = re.compile(r"^[A-Z]")
_STRONG = re.compile(r"^.+(?:[A-Z].*[a-z]|[a-z].*[A-Z]|\d)")  # iPhone, GPT-5, H100, OpenAI

_STOP = {
    "a",
    "an",
    "the",
    "i",
    "it",
    "its",
    "he",
    "she",
    "they",
    "we",
    "you",
    "and",
    "but",
    "or",
    "nor",
    "so",
    "yet",
    "if",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "to",
    "with",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "has",
    "have",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "may",
    "might",
    "this",
    "that",
    "these",
    "those",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    # Sentence-starters that survive true-casing in short texts.
    "now",
    "here",
    "there",
    "then",
    "when",
    "while",
    "how",
    "why",
    "what",
    "who",
    "which",
    "not",
    "no",
    "yes",
    "all",
    "both",
    "each",
    "more",
    "most",
    "some",
    "other",
    "notably",
    "meanwhile",
    "however",
    "although",
    "because",
    "since",
    "after",
    "before",
    "during",
    "under",
    "over",
    "about",
    "against",
    "between",
    "through",
    "without",
    "within",
    "get",
    "got",
    "go",
    "going",
    "make",
    "made",
    "take",
    "took",
    "see",
    "say",
    "said",
    "says",
    "new",
    "first",
    "last",
    "next",
    "just",
    "also",
    "still",
    "even",
    "only",
    "via",
    "per",
    "plus",
    "free",
    "best",
    "top",
    "think",
    "thanks",
    "read",
    "update",
    "updated",
    "exclusive",
    "breaking",
    "report",
    "reports",
    "review",
    "deal",
    "deals",
    "up",
    "out",
    "off",
}


def extract_entities(title: str, body: str | None = None, *, limit: int = 12) -> list[str]:
    text = f"{title}\n{body[:2000]}" if body else title
    # Split only at punctuation followed by whitespace (or line end), so
    # internal dots survive: "GPT-5.6" is one token, not two sentences.
    sentences = re.split(r"[.!?;:](?:\s+|$)|\n", text)
    all_tokens = [t.strip(".,&-") for s in sentences for t in _TOKEN.findall(s)]
    lowercase_seen = {t.lower() for t in all_tokens if t and not _CAP.match(t)}

    def is_entity(tok: str) -> bool:
        if not tok or tok.lower() in _STOP or len(tok) < 2:
            return False
        if _STRONG.match(tok):
            return True  # internal caps or digits: iPhone, GPT-5.6, H100
        # Capitalised AND never seen lowercase in this article's own text.
        return bool(_CAP.match(tok)) and tok.lower() not in lowercase_seen

    # Merge adjacent entity tokens into spans, never across a sentence
    # boundary ("Tim Cook" merges; "...Luna. OpenAI said..." must not).
    entities: dict[str, None] = {}
    for sentence in sentences:
        run: list[str] = []
        for tok in (t.strip(".,&-") for t in _TOKEN.findall(sentence)):
            if is_entity(tok):
                run.append(tok)
                continue
            if run:
                entities.setdefault(" ".join(run).lower(), None)
                run = []
        if run:
            entities.setdefault(" ".join(run).lower(), None)
    return list(entities)[:limit]


def entity_tokens(entities: list[str]) -> set[str]:
    """Flatten spans to words for overlap gating: outlets segment names
    differently ('apple raises trade-in' vs 'apple') but share the tokens."""
    return {w for e in entities for w in e.lower().split() if w not in _STOP}
