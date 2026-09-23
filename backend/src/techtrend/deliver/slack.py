"""The Slack Web API client -- chat.postMessage and nothing else.

httpx, not slack_sdk: one endpoint does not justify a dependency, and the
error taxonomy below is the part that actually matters.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from techtrend.platform import queue
from techtrend.platform.config import settings

_POST = "https://slack.com/api/chat.postMessage"
_REPLIES = "https://slack.com/api/conversations.replies"
_LIST = "https://slack.com/api/conversations.list"
_PERMALINK = "https://slack.com/api/chat.getPermalink"

# chat.postMessage accepts "#name" or an id; chat.delete, conversations.replies
# and chat.getPermalink all require the ID. Resolved once, then cached for the
# process -- a channel id does not change under a running worker.
_CHANNEL_IDS: dict[str, str] = {}

# Retrying these never helps: the token, the scope or the channel is wrong, and
# a human has to fix it. Dead-letter immediately rather than burn the queue.
_FATAL = frozenset(
    {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "missing_scope",
        "channel_not_found",
        "not_in_channel",
        "is_archived",
        "msg_too_long",
        "invalid_blocks",
    }
)


def _raise_for(data: dict[str, Any]) -> None:
    """Slack signals failure in a 200 body. Split it by the taxonomy above."""
    if data.get("ok"):
        return
    err = str(data.get("error", "unknown"))
    if err in _FATAL:
        raise queue.FatalError(f"slack: {err}")
    raise queue.RetryableError(f"slack: {err}")


class SlackClient:
    def __init__(self) -> None:
        token = settings().slack_bot_token
        if token is None:
            raise queue.FatalError("TT_SLACK_BOT_TOKEN is unset")
        self._headers = {
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    async def post(
        self,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        unfurl: bool = True,
    ) -> str:
        """Post one message; return its `ts`. `text` is the notification
        fallback and the accessible version, so it is never optional."""
        # Unfurl ON by default, and that default is load-bearing for a story
        # card: Slack renders the publisher's own preview (blurb, byline,
        # image) from their og: tags, so the card carries ONLY what the unfurl
        # cannot know -- the link and the topics.
        #
        # Pass unfurl=False for a message whose links are Slack permalinks.
        # Slack expands those into quoted copies of the linked message, so a
        # digest of twenty links would bury its own text under five previews
        # of stories the reader already scrolled past. The link is the point
        # there; the preview is noise.
        body: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "unfurl_links": unfurl,
            "unfurl_media": unfurl,
        }
        if blocks is not None:
            body["blocks"] = blocks
        if thread_ts is not None:
            body["thread_ts"] = thread_ts

        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            try:
                resp = await c.post(_POST, headers=self._headers, json=body)
            except httpx.HTTPError as e:
                raise queue.RetryableError(f"slack unreachable: {e!r}") from e

        # 429 carries Retry-After, but the queue's own backoff already spaces
        # attempts further apart than Slack's per-channel limit requires.
        if resp.status_code != httpx.codes.OK:
            raise queue.RetryableError(f"slack http {resp.status_code}")

        data = resp.json()
        _raise_for(data)
        return str(data["ts"])

    async def channel_id(self, channel: str) -> str:
        """Resolve "#name" to a channel id. Ids pass through untouched."""
        if not channel.startswith("#"):
            return channel
        if hit := _CHANNEL_IDS.get(channel):
            return hit
        cursor = ""
        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            while True:
                params = {"types": "public_channel", "limit": 1000, "exclude_archived": "true"}
                if cursor:
                    params["cursor"] = cursor
                body = (await c.get(_LIST, headers=self._headers, params=params)).json()
                _raise_for(body)
                for ch in body.get("channels", []):
                    _CHANNEL_IDS[f"#{ch['name']}"] = ch["id"]
                if hit := _CHANNEL_IDS.get(channel):
                    return hit
                cursor = body.get("response_metadata", {}).get("next_cursor") or ""
                if not cursor:
                    raise queue.FatalError(f"channel not found: {channel}")

    async def permalink(self, channel: str, ts: str) -> str | None:
        """A durable URL for one message. None if Slack will not produce one."""
        cid = await self.channel_id(channel)
        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            body = (
                await c.get(
                    _PERMALINK, headers=self._headers, params={"channel": cid, "message_ts": ts}
                )
            ).json()
        return body.get("permalink") if body.get("ok") else None

    async def replies(self, channel: str, thread_ts: str, limit: int = 30) -> list[dict[str, Any]]:
        """Fetch a thread. `channel` must be an ID (C...), not a #name --
        conversations.* resolve by ID only, unlike chat.postMessage."""
        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            try:
                resp = await c.get(
                    _REPLIES,
                    headers=self._headers,
                    params={"channel": channel, "ts": thread_ts, "limit": limit},
                )
            except httpx.HTTPError as e:
                raise queue.RetryableError(f"slack unreachable: {e!r}") from e
        if resp.status_code != httpx.codes.OK:
            raise queue.RetryableError(f"slack http {resp.status_code}")
        data = resp.json()
        if not data.get("ok"):
            err = str(data.get("error", "unknown"))
            if err in _FATAL:
                raise queue.FatalError(f"slack: {err}")
            raise queue.RetryableError(f"slack: {err}")
        return list(data.get("messages", []))


# Highlighting is a backticked span: Slack renders it in a tinted box, which
# catches the eye in a way bold does not. The prompt asks for backticks; these
# fold either bold dialect into one if a model reaches for emphasis instead.
# `**md**` is Markdown's bold, `*slack*` is Slack's -- both mean "emphasis", and
# here emphasis means code.
#
# The \S lookarounds are load-bearing: they require non-space just inside each
# delimiter, so a lone asterisk in ordinary prose (a footnote marker, a `*.py`
# glob) is never swallowed into markup.
_MD_BOLD = re.compile(r"\*\*+(?=\S)(.+?)(?<=\S)\*\*+", re.S)
_SLACK_BOLD = re.compile(r"(?<!\*)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\*)")
_MD_UNDER = re.compile(r"__(?=\S)(.+?)(?<=\S)__", re.S)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}[ \t]+", re.M)
_MD_BULLET = re.compile(r"^\s{0,3}[-*+][ \t]+", re.M)


def to_mrkdwn(text: str) -> str:
    """Normalise model output into Slack's mrkdwn, emphasis folded to code."""
    text = _MD_BULLET.sub("", text)  # before the bold rules: `* item` is not emphasis
    text = _MD_BOLD.sub(r"`\1`", text)
    text = _SLACK_BOLD.sub(r"`\1`", text)
    text = _MD_UNDER.sub(r"`\1`", text)
    text = _MD_HEADING.sub("", text)
    return text.strip()


_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^[\s|:\-]+$")


def _cells(line: str) -> list[str]:
    """Split one markdown table row. Leading and trailing pipes are borders,
    not empty cells."""
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


def _fixed_width_table(rows: list[list[str]]) -> str:
    """A markdown table as an aligned monospace block.

    Slack renders NO table. A pipe grid posted as mrkdwn is literal text in a
    proportional font, so the columns wander and the thing is unreadable --
    which is exactly what shipped. A fenced code block is the one place Slack
    uses a fixed-width font, so padded columns actually line up there.

    Emphasis is stripped from the cells: inside a code block Slack renders no
    bold, so `*Outlier*` would show its asterisks.
    """
    width = len(max(rows, key=len))
    grid = [r + [""] * (width - len(r)) for r in rows]
    # `html.unescape` matters INSIDE the fence specifically: Slack decodes
    # entities in ordinary mrkdwn but not in a code block, so `&amp;` shows
    # its own markup there. It also skews the padding, since `&amp;` measures
    # five characters where `&` measures one.
    clean = [
        [html.unescape(_MD_BOLD.sub(r"\1", c)).replace("*", "").replace("`", "") for c in r]
        for r in grid
    ]
    # Cap a column so one long cell cannot push every other column off screen.
    caps = [min(24, max(len(r[i]) for r in clean)) for i in range(width)]
    out = []
    for n, row in enumerate(clean):
        cells = [
            (c if len(c) <= caps[i] else c[: caps[i] - 1] + "\u2026").ljust(caps[i])
            for i, c in enumerate(row)
        ]
        out.append("  ".join(cells).rstrip())
        if n == 0:  # a rule under the header, drawn rather than transcribed
            out.append("  ".join("-" * w for w in caps))
    return "```\n" + "\n".join(out) + "\n```"


def _tables_to_blocks(text: str) -> str:
    """Rewrite every markdown table in `text` as a monospace block."""
    out: list[str] = []
    rows: list[list[str]] = []

    def flush() -> None:
        if rows:
            out.append(_fixed_width_table(rows))
            rows.clear()

    for line in text.split("\n"):
        if _TABLE_LINE.match(line):
            # `| :--- | :--- |` is drawing, not data.
            if not _TABLE_RULE.match(line):
                rows.append(_cells(line))
            continue
        flush()
        out.append(line)
    flush()
    return "\n".join(out)


def to_slack_report(text: str) -> str:
    """Model markdown -> Slack mrkdwn, KEEPING the structure.

    The opposite job from `to_mrkdwn`, which strips headings and bullets and
    folds bold into code spans. That is right for a three-sentence summary,
    where emphasis is the only structure there is. It is wrong for a research
    brief: a report of six sections and seventeen platforms arrived as one
    unbroken wall, because every heading and bullet the model wrote was
    deleted on the way out.

    Slack has no heading syntax, so a heading becomes bold on its own line --
    which is what a heading looks like in Slack, and what Slack's own product
    does. Markdown bullets become the literal bullet character, because
    `- item` renders as a dash and `• item` renders as a list.
    """

    # Headings first: `## 2. Fields` -> `*2. Fields*`. Done before the bold
    # rules so the line is not left with stray asterisks to fold.
    def _head(m: re.Match[str]) -> str:
        title = m.group(2).strip().rstrip("*").strip()
        return f"*{title}*" if title else ""

    # `[ \t]*$`, not `\s*$`: `\s` matches newlines, so the greedy version ate
    # the blank line after every heading and welded it to its own paragraph.
    text = re.sub(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*$", _head, text, flags=re.M)
    text = _MD_BOLD.sub(r"*\1*", text)  # **x** -> *x*, Slack's own bold
    text = _MD_UNDER.sub(r"*\1*", text)
    # `- item`, `* item`, `+ item` -> `• item`, indentation preserved so a
    # nested list still reads as nested.
    text = re.sub(r"^(\s{0,8})[-*+][ \t]+", r"\1• ", text, flags=re.M)
    # Tables LAST: the cell contents have had their emphasis normalised by
    # now, and the code block that follows must not have Slack markup inside.
    return _tables_to_blocks(text).strip()


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def decode_title(s: str) -> str:
    """Publisher titles arrive with HTML entities intact: `Here&#8217;s`.

    Public because the hourly report builds its own link text and needs the
    same decode; a second copy of `html.unescape` is how one surface quietly
    starts shipping `&amp;#8217;` while the other does not.
    """
    return html.unescape(s)


_decode = decode_title


def _esc_only(s: str) -> str:
    """Escape for Slack. Input must already be decoded."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc(s: str) -> str:
    """Slack consumes &, < and > as markup even inside plain text.

    Decode first: feed titles arrive with HTML entities intact ("&#8220;"), and
    escaping those directly ships a literal "&amp;#8220;" to the channel.
    """
    return html.unescape(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def story_blocks(
    *,
    title: str,
    url: str,
    site: str,
    source_count: int,
    topics: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    """Render one story as a link plus its provenance.

    Deliberately NOT the blurb and NOT the image: Slack unfurls the URL and
    renders those from the publisher's own og: tags. Anything repeated here
    would appear twice in the channel. What survives is what the unfurl has
    no way to know -- which topics matched, and how many outlets carried it.
    """
    # Decode BEFORE truncating: `_esc` expands & to &amp;, so escaping first
    # then cutting at 200 can slice an entity in half. The fallback gets the
    # same treatment as the heading -- it is not a spare copy of the raw title,
    # it is what Slack shows in push notifications and message previews, so a
    # raw `&#8217;` here reaches every phone in the channel.
    plain = _trunc(_decode(title), 200)
    heading = f"<{url}|*{_esc_only(plain)}*>"

    meta = [_esc(site)]
    if source_count > 1:
        meta.append(f"{source_count} sources")
    if topics:
        meta.append(" ".join(f"`{_esc(t)}`" for t in topics))

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": heading}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(meta)}]},
    ]
    return _esc_only(plain), blocks


def followup_text(source_count: int) -> str:
    """A story that keeps getting picked up is itself the signal."""
    return f"Now covered by *{source_count}* sources."
