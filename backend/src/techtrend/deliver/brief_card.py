"""The channel card for a brief: the few lines a teammate reads every day.

The full report -- fifteen to forty thousand characters and its tables --
goes in the card's thread. The channel itself carries one short card per
topic: a headline, up to three takeaways, what is new with how crowded it
is, and one thing to do today. Eight briefs a day used to be a wall of text
nobody scrolled; eight cards is one screen.

The card is a summary of the report that is posted with it, written by one
small non-search model call. If that call fails or returns something that
cannot be checked, the card is built from the report's own sentences
instead: a card always posts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from techtrend.ai import gemini
from techtrend.deliver import brief_quality as quality
from techtrend.deliver.slack import Block
from techtrend.platform import telemetry
from techtrend.platform.config import settings
from techtrend.topic.match import blocked, searchable

LABELS = ("EARLY", "SPREADING", "CROWDED")
HEADLINE_MAX = 110
POINT_MAX = 220
ACTION_MAX = 160
QUIET = "No major changes in the last 7 days."


@dataclass(frozen=True)
class NewItem:
    text: str
    label: str = ""


@dataclass(frozen=True)
class Card:
    headline: str
    points: list[str] = field(default_factory=list)
    new: list[NewItem] = field(default_factory=list)
    action: str = ""
    generated: bool = True  # False: built from the report's sentences


_SYSTEM = """You write the short daily card for a research report that is posted
in a team chat. The full report is posted in the card's thread; the card is
what people read in the channel.

Write ONLY from the report below. Add nothing that is not in it.
Reader: a smart adult who reads English as a second language. Short, plain
sentences. No idioms. No hype.

Return ONLY a JSON object, no other text:
{"headline": "...", "points": ["...", "..."],
 "new": [{"text": "...", "label": "EARLY"}], "action": "..."}

- headline: the single most important thing today, at most 80 characters.
- points: up to 3 key takeaways. Each is ONE short sentence of at most 180
  characters, with its YYYY-MM-DD date when the report gives one.
- new: up to 3 items from the last 7 days only, from the report's NEW SINCE
  LAST WEEK section, each one short sentence with its YYYY-MM-DD date and
  the label the report gave it (EARLY, SPREADING or CROWDED). Empty list if
  the report says nothing is new.
- action: the one thing a reader should do today, at most 110 characters, or
  an empty string if the report recommends nothing.
Never ask a question. Never address the reader as "you" in the headline."""


def _trim(value: Any, n: int) -> str:
    s = " ".join(str(value or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def parse(raw: str) -> Card | None:
    """The model's JSON as a Card, trimmed to the limits; None if unusable."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(d, dict) or not str(d.get("headline") or "").strip():
        return None
    points = [_trim(p, POINT_MAX) for p in (d.get("points") or []) if str(p).strip()][:3]
    new = []
    for item in (d.get("new") or [])[:3]:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            label = str(item.get("label") or "").upper()
            new.append(NewItem(_trim(item["text"], POINT_MAX), label if label in LABELS else ""))
    return Card(
        headline=_trim(d["headline"], HEADLINE_MAX),
        points=points,
        new=new,
        action=_trim(d.get("action"), ACTION_MAX),
    )


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_])")
_NEW_HEAD = re.compile(r"NEW SINCE LAST WEEK\**\s*\n+(.+?)(?=\n\s*\n\s*[*#]|\Z)", re.S | re.I)
_LABEL = re.compile(r"\b(EARLY|SPREADING|CROWDED)\b")


def _sentences(text: str) -> list[str]:
    # Heading-only lines first: "*OPEN PROGRAMS*" has no full stop, so once
    # lines are joined it would weld itself onto the next sentence.
    text = re.sub(r"^\s*(\*[^*\n]+\*|#+ [^\n]+)\s*$", "", text, flags=re.M)
    flat = re.sub(r"[*_`#|]+", "", text)
    flat = re.sub(r"^\s*[-•]\s*", "", flat, flags=re.M)
    return [s.strip() for s in _SENT.split(" ".join(flat.split())) if len(s.strip()) > 20]


def fallback(report: str) -> Card:
    """A card from the report's own sentences, for when the model call fails.

    The headline is the first sentence of NEW SINCE LAST WEEK when there is
    one, else the report's first sentence; the points are the next ones.
    Nothing is invented, so nothing needs checking beyond what the report got.
    """
    m = _NEW_HEAD.search(report)
    new_sents = _sentences(m.group(1)) if m else []
    body_sents = _sentences(report[m.end() :] if m else report)
    first = (new_sents or body_sents or ["Today's report is in the thread."])[0]
    points = [_trim(s, POINT_MAX) for s in (new_sents[1:] + body_sents)[:3]]
    new = [
        NewItem(_trim(s, POINT_MAX), lm.group(1) if (lm := _LABEL.search(s)) else "")
        for s in new_sents[1:3]
        if _LABEL.search(s)
    ]
    return Card(headline=_trim(first, HEADLINE_MAX), points=points, new=new, generated=False)


def _card_text(card: Card) -> str:
    return "\n".join([card.headline, *card.points, *(n.text for n in card.new), card.action])


def acceptable(card: Card) -> bool:
    """The same gates the report passes: no question, nothing on the block list."""
    t = _card_text(card)
    return not quality.asks_reader(t) and not blocked(
        searchable(t, None, []), settings().block_terms
    )


def only_recent(card: Card, today: date) -> Card:
    """Drop "new" items whose every date is more than 7 days old.

    The 2026-11-17 dry run put "OpenAI acquired Promptfoo (2026-03-09)" under
    New this week. An item with no date is kept: the report put it there.
    """
    cutoff = today - timedelta(days=7)
    keep = [n for n in card.new if not (ds := quality.find_dates(n.text)) or max(ds) >= cutoff]
    return replace(card, new=keep)


async def summarize(report: str, today: date, *, name: str = "") -> Card:
    """The card for `report`: the model's summary if usable, else the fallback."""
    user = f"Today's date is {today.isoformat()}.\n\nREPORT:\n{report[:60000]}"
    try:
        raw, _, _ = await gemini.write(_SYSTEM, user, model=settings().gemini_write_model)
        card = parse(raw)
    except Exception:  # noqa: BLE001 - a card always posts; the fallback is it
        telemetry.log.warning("brief.card_failed", name=name, exc_info=True)
        card = None
    if card is not None:
        card = only_recent(card, today)
    if card is not None and acceptable(card):
        return card
    if card is not None:
        telemetry.log.warning("brief.card_rejected", name=name)
    fb = fallback(report)
    return (
        fb if acceptable(fb) else Card(headline="Today's report is in the thread.", generated=False)
    )


def card_blocks(
    card: Card,
    *,
    title: str,
    today: date,
    searches: int,
    source_count: int,
    flags: list[str],
) -> tuple[str, list[Block]]:
    """(notification text, blocks) for the channel card."""
    heading = _trim(f"📊 {title} — {today.strftime('%a %b')} {today.day}", 150)
    lines: list[str] = [*flags, f"*{_esc(card.headline)}*"]
    body: list[str] = []
    for p in card.points:
        body.append(f"• {_esc(p)}")
    if card.new:
        body.append("")
        body.append("*New this week*")
        for n in card.new:
            tag = f"  `{n.label}`" if n.label else ""
            body.append(f"• {_esc(n.text)}{tag}")
    elif card.generated:
        body.append("")
        body.append(f"_{QUIET}_")
    if card.action:
        body.append("")
        body.append(f"👉 *Today:* {_esc(card.action)}")
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]
    if any(b.strip() for b in body):
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body).strip()}}
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{searches} searches · {source_count} sources · "
                    "full report and tables in the thread 🧵",
                }
            ],
        }
    )
    return f"{title}: {card.headline}", blocks


def _esc(s: str) -> str:
    """Slack mrkdwn escaping: & < > would otherwise start an entity or link."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
