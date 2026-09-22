"""Socket Mode: Slack events over an outbound WebSocket.

The Events API would need Slack to POST to a public HTTPS endpoint. This host
has no domain for TechTrend and Caddy already owns :443, so there is nothing
for Slack to reach. Socket Mode inverts it -- we dial out, Slack pushes events
down the same connection -- which needs no inbound port, no certificate and no
DNS. It also means nothing new is exposed to the internet.

`websockets` rather than `slack_sdk`: the dependency is already here, and the
protocol below is a handshake, an ack and a reconnect loop.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

import httpx
import websockets

from techtrend.deliver import qa
from techtrend.deliver.slack import SlackClient
from techtrend.platform import telemetry
from techtrend.platform.config import settings

_OPEN = "https://slack.com/api/apps.connections.open"
_AUTH = "https://slack.com/api/auth.test"

# Slack drops the socket roughly hourly and asks us to reconnect; that is
# routine, not an error. Backoff applies only to genuine failures.
_BACKOFF_START = 1.0
_BACKOFF_MAX = 60.0


class NotConfigured(RuntimeError):
    """No app-level token, so there is no way in."""


async def _open_socket_url(app_token: str) -> str:
    async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
        r = await c.post(_OPEN, headers={"Authorization": f"Bearer {app_token}"})
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"apps.connections.open: {data.get('error')}")
    return str(data["url"])


async def _bot_id(bot_token: str) -> str | None:
    async with httpx.AsyncClient(timeout=settings().slack_timeout_s) as c:
        r = await c.post(_AUTH, headers={"Authorization": f"Bearer {bot_token}"})
    d = r.json()
    return str(d["bot_id"]) if d.get("ok") and d.get("bot_id") else None


async def _dispatch(client: SlackClient, envelope: dict[str, Any], bot_id: str | None) -> None:
    payload = envelope.get("payload") or {}

    # Slash commands ride the SAME socket as events -- that is what makes
    # `/techtrend` possible here at all, with no public Request URL for Slack
    # to POST to. They arrive as their own envelope type, with the command in
    # the payload rather than in an `event`.
    if envelope.get("type") == "slash_commands":
        from techtrend.deliver import commands

        await commands.handle(payload)
        return

    event = payload.get("event") or {}
    if event.get("type") != "app_mention":
        return
    # Our own messages come back down the socket; answering them would loop.
    if bot_id and event.get("bot_id") == bot_id:
        return
    await qa.handle_mention(client, event, bot_id=bot_id)


async def run(stop: asyncio.Event | None = None) -> None:
    """Listen until stopped. Reconnects for as long as the process lives."""
    s = settings()
    if s.slack_app_token is None or s.slack_bot_token is None:
        raise NotConfigured("TT_SLACK_APP_TOKEN and TT_SLACK_BOT_TOKEN are both required")

    app_token = s.slack_app_token.get_secret_value()
    stop = stop or asyncio.Event()
    client = SlackClient()
    bot_id = await _bot_id(s.slack_bot_token.get_secret_value())
    # Slack redelivers an envelope if an ack is late. Remember recent ones so a
    # redelivery cannot produce a second answer to the same question.
    seen: deque[str] = deque(maxlen=512)
    backoff = _BACKOFF_START

    telemetry.log.info("slackbot.start", bot_id=bot_id)
    while not stop.is_set():
        try:
            url = await _open_socket_url(app_token)
            async with websockets.connect(url, ping_interval=20) as ws:
                backoff = _BACKOFF_START  # a successful connect resets it
                telemetry.log.info("slackbot.connected")
                while not stop.is_set():
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "hello":
                        continue
                    if kind == "disconnect":
                        telemetry.log.info("slackbot.disconnect", reason=msg.get("reason"))
                        break  # routine socket refresh: reconnect immediately
                    envelope_id = msg.get("envelope_id")
                    if envelope_id:
                        # Ack FIRST. Slack wants it within 3 seconds and an
                        # answer takes far longer than that, so the work runs
                        # detached rather than inline.
                        await ws.send(json.dumps({"envelope_id": envelope_id}))
                        if envelope_id in seen:
                            continue
                        seen.append(envelope_id)
                    asyncio.create_task(_dispatch(client, msg, bot_id))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the listener outlives any one failure
            telemetry.log.exception("slackbot.connection_failed", retry_in_s=backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, _BACKOFF_MAX)
    telemetry.log.info("slackbot.stop")
