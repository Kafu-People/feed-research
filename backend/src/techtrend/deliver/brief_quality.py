"""Checks a researched brief must pass before it reaches a channel.

Pure text in, text out -- no model, no Slack -- so each rule is testable on
the exact output that went wrong in the channel:

- the model asked the reader a question instead of writing the report
  (dataannotation, 2026-11-16: "My recommendation: ... requires either 1. 2. 3.");
- relative dates nobody can place ("637 days ago");
- programs listed as open whose deadline had already passed.

The prompt asks for all of this too. These checks are the part that does not
depend on the model listening.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from techtrend.platform.config import settings


def today_local(now: datetime | None = None) -> date:
    """Today in the reader's timezone (America/New_York by default)."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(settings().brief_timezone)).date()


# --------------------------------------------------------------- questions

_ASKS = re.compile(
    r"\b(would you like|do you want|should i\b|shall i\b|let me know (if|whether|which)"
    r"|if you want me to|if you would like me to|say yes|want me to proceed"
    r"|should i proceed|which (option|would you prefer)|please confirm)",
    re.IGNORECASE,
)


def asks_reader(text: str) -> bool:
    """True when the output addresses the reader with a question or an offer.

    A report ends on a summary, never on "?": the last non-empty line ending
    in a question mark is itself the signal, phrase list or not.
    """
    if _ASKS.search(text):
        return True
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return False
    last = re.sub(r"[*_`]+", "", lines[-1]).strip()
    return last.endswith("?")


def only_question(text: str) -> bool:
    """A reply that is nothing but a question or an offer -- never postable.

    Short, and asking: the Nov 16 dataannotation post was 1,676 characters of
    "what I can and cannot find" ending in options. A real report on any of
    these topics is several thousand characters.
    """
    return asks_reader(text) and len(text.strip()) < 2500


# ------------------------------------------------------------------- dates

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MDY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.I)


def find_dates(text: str) -> list[date]:
    """Every absolute calendar date written in `text`, in any common form."""
    out: list[date] = []
    for m in _ISO.finditer(text):
        out += _safe(int(m[1]), int(m[2]), int(m[3]))
    for m in _MDY.finditer(text):
        out += _safe(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
    for m in _DMY.finditer(text):
        out += _safe(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    return out


def _safe(y: int, mo: int, d: int) -> list[date]:
    try:
        return [date(y, mo, d)]
    except ValueError:
        return []


_AGO = re.compile(
    r"\b(?:posted\s+|published\s+|updated\s+)?(\d+|an?|one)\s+(day|week|month|year)s?\s+ago\b",
    re.IGNORECASE,
)
_VAGUE = re.compile(r"\((recent|recently|recent weeks)\)", re.IGNORECASE)


def absolutize_relative_dates(text: str, today: date) -> tuple[str, int]:
    """'637 days ago' -> '2025-02-18'. Returns (text, how many were rewritten).

    Days and weeks convert exactly. Months and years only to the month,
    written 'about YYYY-MM', because '3 months ago' does not name a day. A
    bare '(recent)' in place of a date becomes '(date unknown)', which is
    what it actually means.
    """
    n = 0

    def ago(m: re.Match[str]) -> str:
        nonlocal n
        raw = m[1].lower()
        k = 1 if raw in ("a", "an", "one") else int(raw)
        unit = m[2].lower()
        n += 1
        if unit == "day":
            return (today - timedelta(days=k)).isoformat()
        if unit == "week":
            return (today - timedelta(weeks=k)).isoformat()
        months = k if unit == "month" else 12 * k
        y, mo = divmod(today.year * 12 + today.month - 1 - months, 12)
        return f"about {y:04d}-{mo + 1:02d}"

    text = _AGO.sub(ago, text)

    def vague(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        return "(date unknown)"

    return _VAGUE.sub(vague, text), n


# ----------------------------------------------------------------- expired

# A deadline word with its date ATTACHED: "through 2026-07-27", "deadline:
# Nov 2, 2026", "closes on 2 November 2026". The first version took any
# deadline word and any past date in the same sentence, and the dry run of
# 2026-11-17 removed real news with it -- "OpenAI announced on 2026-11-03 it
# was quadrupling rewards through its bug bounty program" has both.
_DEADLINE_WORD = (
    r"deadlines?|closes|closing|closed|close|apply by|due(?: by)?|ends|ended|ending"
    r"|runs? through|ran through|through|until|till|expires?|expired|last day"
)
_ANY_DATE = (
    r"(?:\d{4}-\d{2}-\d{2}"
    rf"|(?:{_MONTH_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_RE})\.?,?\s+\d{{4}}"
    # No year: "through September 16th" (the 2026-11-17 redteam dry run).
    # Only ever matched next to a deadline word, and read as this year.
    rf"|(?:{_MONTH_RE})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b)"
)
_NO_YEAR = re.compile(rf"({_MONTH_RE})\.?\s+(\d{{1,2}})", re.IGNORECASE)
_ATTACHED = re.compile(
    rf"\b(?:{_DEADLINE_WORD})\b[\s:,(]*(?:on\s+|is\s+|was\s+|date\s+|of\s+)?({_ANY_DATE})",
    re.IGNORECASE,
)
# A cell that says the item is over: at its start ("Closed"), in brackets
# after a date range ("15 Oct - 5 Nov 2026 (closed)", the 2026-11-17 dry run),
# or as "now closed" / "has ended".
_CLOSED_CELL = re.compile(
    r"^\W*(closed|expired|ended|finished|no longer (open|accepting))\b"
    r"|\((closed|expired|ended|finished)\)"
    r"|\b(now|has|have been|was) (closed|ended|expired)\b",
    re.I,
)
_OPEN_CELL = re.compile(r"^\W*(open|rolling|ongoing|active|accepting)\b", re.I)
_DEADLINE_HEADER = re.compile(r"deadline|closes|closing|ends|end date|due", re.I)
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_RULE = re.compile(r"^[\s|:\-]+$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*_])")


def _attached_past(s: str, today: date) -> bool:
    """A deadline word whose own date is before today."""
    for m in _ATTACHED.finditer(s):
        dates = find_dates(m[1])
        if not dates and (n := _NO_YEAR.match(m[1])):
            dates = _safe(today.year, _MONTHS[n[1].lower()], int(n[2]))
        if any(d < today for d in dates):
            return True
    return False


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def drop_expired(text: str, today: date) -> tuple[str, list[str]]:
    """Remove programs whose deadline has passed and rows marked closed.

    A table row goes whole when its status says closed, when its deadline
    column holds a past date, or when it names an attached past deadline and
    does not say it is still open (a program can be open while one of its
    challenges has ended). In prose, only the sentence with the expired
    deadline goes, so a paragraph keeps its other facts.
    Returns (text, what was removed).
    """
    removed: list[str] = []
    out: list[str] = []
    deadline_cols: set[int] = set()
    in_table = False
    for line in text.split("\n"):
        if _TABLE_LINE.match(line):
            if _RULE.match(line):
                out.append(line)
                continue
            cells = _cells(line)
            if not in_table:  # the header row of a new table
                in_table = True
                deadline_cols = {i for i, c in enumerate(cells) if _DEADLINE_HEADER.search(c)}
                out.append(line)
                continue
            past_column = any(
                d < today for i in deadline_cols if i < len(cells) for d in find_dates(cells[i])
            )
            still_open = any(_OPEN_CELL.match(c) for c in cells)
            if (
                any(_CLOSED_CELL.search(c) for c in cells)
                or past_column
                or (_attached_past(line, today) and not still_open)
            ):
                removed.append(line.strip())
                continue
            out.append(line)
            continue
        in_table = False
        if not _ATTACHED.search(line):
            out.append(line)
            continue
        kept = []
        for sentence in _SENTENCE.split(line):
            if _attached_past(sentence, today):
                removed.append(sentence.strip())
            else:
                kept.append(sentence)
        if kept:
            out.append(" ".join(kept))
    return "\n".join(out), removed
