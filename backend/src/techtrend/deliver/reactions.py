"""Team feedback on #feed-ai-news: 👍 / 👎 on a story's thread reply.

A reaction is recorded against the one story its reply carries, together with
that story's category and publisher. The ranking reads it back as a small,
capped boost: a team that keeps 👍-ing funding news sees funding a little
higher in each edition. Feedback reorders; it never hides a story -- every
story is still posted (operator decision 2026-11-17).

Needs the Slack app's `reactions:read` scope and the `reaction_added` /
`reaction_removed` event subscriptions. Without them nothing arrives, the
table stays empty and the boost is zero.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from techtrend.deliver.news_format import category
from techtrend.platform import telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope

UP = {"+1", "thumbsup"}
DOWN = {"-1", "thumbsdown"}
PER_VOTE = 0.02
CAP = 0.15
WINDOW_DAYS = 30

# The reply a reaction landed on -> its story. `summary_ts` is the story's
# own thread reply in editions mode.
_STORY = text("""
    SELECT st.id, a.title, a.description, a.site_id, st.source_count
      FROM slack_posts sp
      JOIN stories st ON st.id = sp.story_id
      JOIN articles a ON a.id = st.display_article_id
     WHERE sp.channel = :ch AND sp.summary_ts = :ts
     LIMIT 1
""")
_ADD = text("""
    INSERT INTO slack_reactions (story_id, user_id, vote, category, site_id)
    VALUES (:story, :user, :vote, :cat, :site)
    ON CONFLICT (story_id, user_id, vote) DO NOTHING
""")
_REMOVE = text(
    "DELETE FROM slack_reactions WHERE story_id = :story AND user_id = :user AND vote = :vote"
)
_TOTALS = text("""
    SELECT 'c' AS kind, category AS key, sum(vote) AS net
      FROM slack_reactions WHERE created_at > now() - make_interval(days => :days)
     GROUP BY category
    UNION ALL
    SELECT 's', site_id::text, sum(vote)
      FROM slack_reactions
     WHERE created_at > now() - make_interval(days => :days) AND site_id IS NOT NULL
     GROUP BY site_id
""")


def vote_for(reaction: str) -> int:
    """+1, -1, or 0 for a reaction we do not count. Skin tones are ignored."""
    name = reaction.split("::", 1)[0]
    return 1 if name in UP else -1 if name in DOWN else 0


async def handle(event: dict[str, Any]) -> bool:
    """Record or remove one reaction event. True when it was counted."""
    vote = vote_for(str(event.get("reaction", "")))
    item = event.get("item") or {}
    channel = settings().slack_channel
    if not vote or item.get("type") != "message" or item.get("channel") != channel:
        return False
    user = str(event.get("user") or "")
    if not user:
        return False
    async with session_scope() as sess:
        row = (
            await sess.execute(
                _STORY,
                {
                    "ch": channel,
                    "ts": str(item.get("ts")),
                },
            )
        ).first()
        if row is None:
            return False  # not a story reply: an edition header, a digest, a brief
        args = {"story": row.id, "user": user, "vote": vote}
        if event.get("type") == "reaction_removed":
            await sess.execute(_REMOVE, args)
        else:
            _, cat = category(row.title, row.description, outlets=row.source_count)
            await sess.execute(_ADD, {**args, "cat": cat, "site": row.site_id})
    telemetry.log.info("reaction.recorded", story=row.id, vote=vote, kind=event.get("type"))
    return True


async def boosts() -> tuple[dict[str, float], dict[int, float]]:
    """(by category label, by site id) net feedback, as ranking adjustments."""
    by_cat: dict[str, float] = {}
    by_site: dict[int, float] = {}
    async with session_scope() as sess:
        for r in (await sess.execute(_TOTALS, {"days": WINDOW_DAYS})).all():
            value = max(-CAP, min(CAP, PER_VOTE * float(r.net or 0)))
            if r.kind == "c":
                by_cat[str(r.key)] = value
            else:
                by_site[int(r.key)] = value
    return by_cat, by_site


def boost_for(row: Any, by_cat: dict[str, float], by_site: dict[int, float]) -> float:
    """One story's adjustment: category plus publisher, capped together."""
    _, cat = category(row.title, getattr(row, "description", None), outlets=row.source_count)
    total = by_cat.get(cat, 0.0) + by_site.get(int(getattr(row, "site_id", 0) or 0), 0.0)
    return max(-CAP, min(CAP, total))
