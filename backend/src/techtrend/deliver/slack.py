"""The Slack Web API client -- chat.postMessage and nothing else.

httpx, not slack_sdk: one endpoint does not justify a dependency, and the
error taxonomy below is the part that actually matters.
"""

from __future__ import annotations

import html
from typing import Any

import httpx

from techtrend.platform import queue
from techtrend.platform.config import settings

_API = "https://slack.com/api/chat.postMessage"

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
    ) -> str:
        """Post one message; return its `ts`. `text` is the notification
        fallback and the accessible version, so it is never optional."""
        # Unfurling ON by design: Slack renders the publisher's own preview
        # (blurb, byline, image) from their og: tags. Our message therefore
        # carries ONLY what the unfurl cannot know -- the link and the topics.
        body: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "unfurl_links": True,
            "unfurl_media": True,
        }
        if blocks is not None:
            body["blocks"] = blocks
        if thread_ts is not None:
            body["thread_ts"] = thread_ts

        async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
            try:
                resp = await c.post(_API, headers=self._headers, json=body)
            except httpx.HTTPError as e:
                raise queue.RetryableError(f"slack unreachable: {e!r}") from e

        # 429 carries Retry-After, but the queue's own backoff already spaces
        # attempts further apart than Slack's per-channel limit requires.
        if resp.status_code != httpx.codes.OK:
            raise queue.RetryableError(f"slack http {resp.status_code}")

        data = resp.json()
        if not data.get("ok"):
            err = str(data.get("error", "unknown"))
            if err in _FATAL:
                raise queue.FatalError(f"slack: {err}")
            raise queue.RetryableError(f"slack: {err}")
        return str(data["ts"])


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


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
    heading = f"<{url}|*{_esc(_trunc(title, 200))}*>"

    meta = [_esc(site)]
    if source_count > 1:
        meta.append(f"{source_count} sources")
    if topics:
        meta.append(" ".join(f"`{_esc(t)}`" for t in topics))

    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": heading}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(meta)}]},
    ]
    return _trunc(title, 200), blocks


def followup_text(source_count: int) -> str:
    """A story that keeps getting picked up is itself the signal."""
    return f"Now covered by *{source_count}* sources."
