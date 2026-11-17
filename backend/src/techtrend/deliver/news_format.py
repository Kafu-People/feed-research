"""What #feed-ai-news looks like: editions, story lines and thread replies.

Pure formatting -- rows and summaries in, Slack blocks out -- so every rule
here is testable without Slack, the database or a model.

The channel used to be one "hourly report" per hour, day and night: 14 to 42
posts a day, most with one story, each story a five-sentence paragraph tagged
"AI models & labs" whatever it was about. An edition is three posts a day:
one scannable line per story in the channel, the full summaries in the thread.
"""

from __future__ import annotations

import re
from typing import Any

from techtrend.deliver.slack import Block, decode_title, to_mrkdwn

# (emoji, label, pattern). First match wins, so the order is the tie-break:
# a security story about a lawsuit is filed under policy, a funding round for
# a security company under funding. Word boundaries, because substrings lie:
# "app" is in "Apple", "ban" in "bank", "api" in "rapid".
CATEGORIES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "💰",
        "funding",
        re.compile(
            r"\b(raises?|raised|funding|series [a-f]\b|seed round|valuation|ipo\b"
            r"|invest(s|ed|ment|ing|or|ors)?\b|acquir(e|es|ed|ing|ition)|buys\b)"
        ),
    ),
    (
        "⚖️",
        "policy & law",
        re.compile(
            r"\b(sues?|sued|lawsuit|court|judge|regulat\w*|laws?\b|bill\b|bans?\b|ftc\b"
            r"|doj\b|antitrust|senate|congress|eu\b|export controls?|attorneys? general"
            r"|department of justice|justice department|legislat\w*|lawmakers?|attorneys?\b)"
        ),
    ),
    (
        "🔐",
        "security",
        re.compile(
            r"\b(hack\w*|breach\w*|vulnerab\w*|exploit\w*|attacks?\b|malware|jailbreak\w*"
            r"|prompt injection|ransomware|red[- ]team\w*|bug bount\w*)"
        ),
    ),
    (
        "💼",
        "jobs & gig work",
        re.compile(
            r"\b(jobs?\b|hiring|layoffs?|laid off|workers?\b|workforce|annotat\w*"
            r"|ai trainers?|contractors?|freelanc\w*|gig\b|remote work|salar\w*|pay\b)"
        ),
    ),
    (
        "🔧",
        "tools & products",
        re.compile(
            r"\b(apps?\b|features?\b|launch(es|ed)?\b|releas(e|es|ed)\b|updates?\b"
            r"|extensions?\b|plugins?\b|browser|open[- ]source|github|api\b)"
        ),
    ),
]
DEFAULT = ("🧠", "models & labs")
HOT = ("🔥", "widely covered")
HOT_OUTLETS = 3
BLURB_MAX = 160


def category(title: str, description: str | None = None, *, outlets: int = 1) -> tuple[str, str]:
    """(emoji, label) for a story, from its own words.

    Three or more outlets on one story outranks what it is about: that is
    the thing a reader scanning the channel most wants flagged.
    """
    if outlets >= HOT_OUTLETS:
        return HOT
    hay = f" {decode_title(title)} {description or ''} ".lower()
    for emoji, label, pattern in CATEGORIES:
        if pattern.search(hay):
            return emoji, label
    return DEFAULT


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def blurb(summary: str | None, description: str | None = None) -> str:
    """One line under the headline: the summary's first sentence.

    The summary's first sentence is the "what happened" by construction (the
    summary prompt leads with it). With no summary, the publisher's own
    description stands in. Backticks are dropped: they render as code.
    """
    src = summary or description or ""
    src = " ".join(src.replace("`", "").split())
    if not src:
        return ""
    first = _SENTENCE_END.split(src, maxsplit=1)[0]
    return first if len(first) <= BLURB_MAX else first[: BLURB_MAX - 1].rstrip() + "…"


def _link(url: str, title: str) -> str:
    # Decode BEFORE escaping: titles arrive with entities ("Here&#8217;s").
    # Slack link text also breaks on a bare | or >.
    safe = decode_title(title).replace("|", "❘").replace(">", "&gt;").replace("<", "&lt;")
    return f"<{url}|{safe}>"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def story_line(r: Any, summary: str | None) -> str:
    """The channel line for one story: emoji, linked headline, reach, blurb."""
    emoji, _ = category(r.title, getattr(r, "description", None), outlets=r.source_count)
    reach = f" — {r.source_count} outlets" if r.source_count > 1 else ""
    line = f"{emoji} *{_link(r.url, r.title)}*{reach}"
    if b := blurb(summary, getattr(r, "description", None)):
        line += f"\n      {_esc(b)}"
    return line


# Slack: 3,000 characters a section (counted after its own escaping), 50
# blocks a message. Story lines are packed into sections well under that.
SECTION_LIMIT = 2500


def _pack(lines: list[str]) -> list[str]:
    out: list[str] = []
    cur = ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > SECTION_LIMIT:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def edition_blocks(
    *,
    name: str,
    when: str,
    rows: list[Any],
    summaries: dict[int, str | None],
    top: int,
    feedback: bool = True,
) -> tuple[str, list[Block]]:
    """(notification text, blocks) for an edition's channel message.

    The top `top` stories, ranked by the caller, as one line each. Everything
    is posted -- the rest, and every full summary, are in the thread.
    """
    n = len(rows)
    heading = f"📰 AI News — {name} · {when} ({n} {'story' if n == 1 else 'stories'})"
    shown = rows[:top]
    lines = [story_line(r, summaries.get(r.id)) for r in shown]
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading[:150], "emoji": True}},
        *[{"type": "section", "text": {"type": "mrkdwn", "text": t}} for t in _pack(lines)],
    ]
    more = n - len(shown)
    footer = [f"+{more} more" if more > 0 else "", "full summaries in the thread 🧵"]
    if feedback:
        footer.append("react 👍 / 👎 on a story in the thread to tune the feed")
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": " · ".join(f for f in footer if f)}],
        }
    )
    titles = "; ".join(decode_title(r.title) for r in shown[:3])
    return f"{heading} — {titles}"[:2000], blocks


def breaking_blocks(r: Any, summary: str | None) -> tuple[str, list[Block]]:
    """A story covered widely enough to post now rather than wait."""
    heading = f"⚡ Breaking — {r.source_count} outlets"
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": story_line(r, summary)}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "full summary in the thread 🧵"}],
        },
    ]
    return f"{heading} — {decode_title(r.title)}"[:2000], blocks


def story_reply_blocks(r: Any, summary: str | None) -> tuple[str, list[Block]]:
    """One thread reply per story: headline, source line, full summary.

    One reply per story, not one long reply, so a 👍 or 👎 lands on exactly
    one story -- that is how a reaction is turned back into feedback.
    """
    emoji, label = category(r.title, getattr(r, "description", None), outlets=r.source_count)
    reach = f" · {r.source_count} outlets" if r.source_count > 1 else ""
    text = f"{emoji} *{_link(r.url, r.title)}*\n_{_esc(r.site)}{reach} · {label}_"
    if summary:
        body = to_mrkdwn(summary)
        text += "\n" + (body if len(body) <= 2400 else body[:2399].rstrip() + "…")
    return decode_title(r.title)[:2000], [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    ]
