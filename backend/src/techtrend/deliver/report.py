"""The weekly report: seven days of the pipeline in, one operator briefing out.

Distinct from the daily digest in both audience and input. The digest is for a
READER and recaps what the channel showed. This is for the OPERATOR and recaps
what the SYSTEM did -- ingest volume, source health, queue depth, delivery --
because the failures that matter here (a feed that died, a stage that stopped)
are invisible in a digest that only ever describes stories that made it through.

Every projection is arithmetic on observed rows, never a model's guess. A
weekly number a reader might act on has to be reproducible from the database,
so nothing in here calls the AI client: a hallucinated trend in a report that
looks authoritative is worse than no report.

Story text surfaced here passes BOTH content gates -- `site_blocked` on the
publisher and `blocked` on the terms -- exactly as notify and match do. A new
delivery surface that skips them is how banned content reaches a reader by the
back door.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from techtrend.platform import telemetry
from techtrend.platform.config import settings, site_blocked
from techtrend.topic.match import blocked, searchable

# Saturday. `datetime.weekday()` is Monday-0, so Saturday is 5.
REPORT_WEEKDAY = 5
REPORT_HOUR = 15


def tz() -> ZoneInfo:
    """The report's clock. Shared with the digest deliberately: two delivery
    surfaces on two different timezones would put the operator's week and the
    reader's day out of step for no reason."""
    return ZoneInfo(settings().digest_timezone)


def week_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """(since, until) for the most recent COMPLETED report week.

    `until` is the latest Saturday REPORT_HOUR local that has already passed;
    `since` is seven days before it. Anchoring on a boundary in the past keeps
    the report reproducible: running it twice, or re-running it days later
    after an outage, covers the same window and yields the same numbers.
    """
    local = (now or datetime.now(UTC)).astimezone(tz())
    anchor = local.replace(hour=REPORT_HOUR, minute=0, second=0, microsecond=0)
    # Days back to the most recent Saturday, then one more week if that
    # Saturday's hour has not yet arrived.
    back = (local.weekday() - REPORT_WEEKDAY) % 7
    until = anchor - timedelta(days=back)
    if until > local:
        until -= timedelta(days=7)
    return until - timedelta(days=7), until


_VOLUME = text("""
    SELECT count(*) FILTER (WHERE fetched_at >= :since AND fetched_at < :until) AS this_week,
           count(*) FILTER (WHERE fetched_at >= :prev  AND fetched_at < :since) AS prev_week,
           count(*) FILTER (WHERE fetched_at >= :since AND fetched_at < :until
                              AND story_id IS NOT NULL) AS grouped,
           count(*) FILTER (WHERE fetched_at >= :since AND fetched_at < :until
                              AND text_key IS NOT NULL) AS body_read
      FROM articles
""")

_DAILY = text("""
    SELECT (fetched_at AT TIME ZONE :zone)::date AS day, count(*) AS n
      FROM articles WHERE fetched_at >= :since AND fetched_at < :until
     GROUP BY 1 ORDER BY 1
""")

_TIERS = text("""
    SELECT si.tier, count(a.id) AS n
      FROM sites si JOIN articles a ON a.site_id = si.id
     WHERE a.fetched_at >= :since AND a.fetched_at < :until
     GROUP BY si.tier ORDER BY si.tier
""")

_SOURCES = text("""
    SELECT si.name, si.domain, si.tier, si.authority, count(a.id) AS n
      FROM sites si
      LEFT JOIN articles a ON a.site_id = si.id
                          AND a.fetched_at >= :since AND a.fetched_at < :until
     GROUP BY si.id, si.name, si.domain, si.tier, si.authority
     ORDER BY n DESC, si.authority DESC
""")

# A feed at or over the failure ceiling is not merely failing: the partial
# index the scheduler polls (ix_endpoints_due) excludes it, so nothing will
# ever retry it. That is a permanent loss of a source, and the reason this
# report separates "failing" from "dropped".
_ENDPOINTS = text("""
    SELECT si.name, si.domain, si.authority, e.kind, e.failure_streak, e.last_status
      FROM endpoints e JOIN sites si ON si.id = e.site_id
     WHERE e.failure_streak > 0
     ORDER BY e.failure_streak DESC, si.authority DESC, si.name
""")

_SITES_NO_ENDPOINT = text("""
    SELECT si.name, si.domain, si.authority
      FROM sites si
     WHERE NOT EXISTS (SELECT 1 FROM endpoints e WHERE e.site_id = si.id)
     ORDER BY si.authority DESC, si.name
""")

_QUEUE = text("SELECT stage, state, count(*) AS n FROM jobs GROUP BY 1, 2 ORDER BY 1, 2")

_STORIES = text("""
    SELECT count(*) AS total,
           count(*) FILTER (WHERE judged_at IS NOT NULL) AS judged,
           max(judged_at) AS last_judged,
           count(*) FILTER (WHERE created_at >= :since AND created_at < :until) AS created_week
      FROM stories
""")

_DELIVERY = text("""
    SELECT count(*) FILTER (WHERE posted_at >= :since AND posted_at < :until) AS posts,
           count(*) FILTER (WHERE posted_at >= :prev  AND posted_at < :since) AS posts_prev,
           count(*) FILTER (WHERE posted_at >= :since AND posted_at < :until
                              AND summary_ts IS NOT NULL) AS with_summary
      FROM slack_posts
""")

_DIGESTS = text("""
    SELECT day, story_count FROM daily_digests
     WHERE posted_at >= :since AND posted_at < :until ORDER BY day
""")

# created_at comes back so the renderer can suppress a week-over-week figure
# for a topic that did not exist for both weeks. A new topic matches the whole
# standing corpus on its first pass, so its opening number is a backfill spike,
# not a week's traffic -- reporting the drop off that spike as a percentage
# reads as a collapse when it is just the backlog draining.
_TOPICS = text("""
    SELECT t.id, t.title, t.subscriber_count, t.created_at,
           count(m.story_id) FILTER (WHERE m.matched_at >= :since
                                       AND m.matched_at < :until) AS n,
           count(m.story_id) FILTER (WHERE m.matched_at >= :prev
                                       AND m.matched_at < :since) AS n_prev,
           avg(m.match_score) FILTER (WHERE m.matched_at >= :since
                                        AND m.matched_at < :until) AS score
      FROM topics t LEFT JOIN matches m ON m.topic_id = t.id
     GROUP BY t.id, t.title, t.subscriber_count, t.created_at
     ORDER BY n DESC, t.title
""")

# Widely-covered first: "the week's biggest" means the story the most distinct
# outlets independently chose to run, which is the only reach signal available
# while the judge stage is not scoring novelty.
_TOP = text("""
    SELECT a.title, a.description, a.entities, si.name AS site, si.domain,
           st.source_count, st.importance
      FROM stories st
      JOIN articles a ON a.id = st.display_article_id
      JOIN sites si ON si.id = a.site_id
     WHERE st.created_at >= :since AND st.created_at < :until
     ORDER BY st.source_count DESC, st.importance DESC NULLS LAST
     LIMIT :cap
""")

_ENGAGEMENT = text("""
    SELECT count(*) FILTER (WHERE at >= :since AND at < :until) AS events,
           count(DISTINCT user_id) FILTER (WHERE at >= :since AND at < :until) AS users
      FROM events
""")


@dataclass
class Story:
    title: str
    site: str
    domain: str
    source_count: int


@dataclass
class Report:
    since: datetime
    until: datetime
    ingested: int = 0
    ingested_prev: int = 0
    grouped: int = 0
    body_read: int = 0
    daily: list[Any] = field(default_factory=list)
    tiers: list[Any] = field(default_factory=list)
    sources_live: list[Any] = field(default_factory=list)
    sources_silent: list[Any] = field(default_factory=list)
    endpoints_failing: list[Any] = field(default_factory=list)
    endpoints_dropped: list[Any] = field(default_factory=list)
    sites_unconfigured: list[Any] = field(default_factory=list)
    queue: list[Any] = field(default_factory=list)
    stories_total: int = 0
    stories_judged: int = 0
    stories_week: int = 0
    last_judged: datetime | None = None
    posts: int = 0
    posts_prev: int = 0
    posts_with_summary: int = 0
    digests: list[Any] = field(default_factory=list)
    topics: list[Any] = field(default_factory=list)
    top: list[Story] = field(default_factory=list)
    gated: int = 0
    banned_publishers: int = 0
    events: int = 0
    users_active: int = 0

    @property
    def delta(self) -> float:
        """Ingest change against the prior week, as a percentage."""
        return (
            0.0
            if not self.ingested_prev
            else 100.0 * (self.ingested - self.ingested_prev) / self.ingested_prev
        )

    @property
    def unjudged(self) -> int:
        return self.stories_total - self.stories_judged


async def collect(sess: Any, since: datetime, until: datetime) -> Report:
    """Every number in the report, in one pass over the database."""
    prev = since - timedelta(days=7)
    args = {"since": since, "until": until, "prev": prev}
    r = Report(since=since, until=until)

    vol = (await sess.execute(_VOLUME, args)).one()
    r.ingested, r.ingested_prev = vol.this_week, vol.prev_week
    r.grouped, r.body_read = vol.grouped, vol.body_read

    zone = settings().digest_timezone
    r.daily = list((await sess.execute(_DAILY, {**args, "zone": zone})).all())
    r.tiers = list((await sess.execute(_TIERS, args)).all())

    for row in (await sess.execute(_SOURCES, args)).all():
        if _banned(row.domain):
            r.banned_publishers += 1
            continue
        (r.sources_live if row.n else r.sources_silent).append(row)

    for row in (await sess.execute(_ENDPOINTS, args)).all():
        if _banned(row.domain):
            continue
        # 10 is the ceiling baked into ix_endpoints_due's WHERE clause.
        (r.endpoints_dropped if row.failure_streak >= 10 else r.endpoints_failing).append(row)

    r.sites_unconfigured = [
        s for s in (await sess.execute(_SITES_NO_ENDPOINT, args)).all() if not _banned(s.domain)
    ]
    r.queue = list((await sess.execute(_QUEUE, args)).all())

    st = (await sess.execute(_STORIES, args)).one()
    r.stories_total, r.stories_judged = st.total, st.judged
    r.last_judged, r.stories_week = st.last_judged, st.created_week

    dl = (await sess.execute(_DELIVERY, args)).one()
    r.posts, r.posts_prev, r.posts_with_summary = dl.posts, dl.posts_prev, dl.with_summary
    r.digests = list((await sess.execute(_DIGESTS, args)).all())
    r.topics = list((await sess.execute(_TOPICS, args)).all())

    eng = (await sess.execute(_ENGAGEMENT, args)).one()
    r.events, r.users_active = eng.events, eng.users

    r.top, r.gated = _gated_top((await sess.execute(_TOP, {**args, "cap": 60})).all())
    return r


def _banned(domain: str | None) -> bool:
    """A publisher the operator banned.

    Their feed necessarily stops returning usable articles, so leaving them in
    the health lists reports our own ban as a system failure -- and puts a
    banned publisher's name on a delivery surface, which is the thing the ban
    exists to prevent. Counted, never named.
    """
    return site_blocked(domain, settings().blocked_sites) is not None


def _gated_top(rows: list[Any], keep: int = 10) -> tuple[list[Story], int]:
    """Apply both content gates, then keep the top `keep` survivors.

    Over-fetched on purpose: gating after the LIMIT would silently shorten the
    list whenever a blocked story ranked highly, which reads as a quiet week
    rather than as the gate doing its job.
    """
    s = settings()
    out: list[Story] = []
    dropped = 0
    for row in rows:
        if ban := site_blocked(row.domain, s.blocked_sites):
            dropped += 1
            telemetry.log.info("report.site_blocked", domain=row.domain, ban=ban)
            continue
        story = searchable(row.title, row.description, list(row.entities or []))
        if hit := blocked(story, s.block_terms):
            dropped += 1
            telemetry.log.info("report.term_blocked", term=hit)
            continue
        out.append(Story(row.title, row.site, row.domain, row.source_count))
        if len(out) == keep:
            break
    return out, dropped


def _pct(n: int, of: int) -> str:
    """A whole-number percentage, safe when the denominator is zero."""
    return "0" if not of else f"{100.0 * n / of:.0f}"


def _bar(n: int, peak: int, width: int = 24) -> str:
    return "#" * max(1, round(width * n / peak)) if n and peak else ""


def render(r: Report) -> str:
    """Markdown. Plain enough to paste into Slack, a file, or a terminal."""
    zone = datetime.now(tz()).strftime("%Z") or settings().digest_timezone
    # The window is carried in UTC and rendered local: a report headed with a
    # local zone label but UTC clock times misstates its own boundaries.
    since_l, until_l = r.since.astimezone(tz()), r.until.astimezone(tz())
    lines: list[str] = []
    add = lines.append

    add(f"# TechTrend Weekly — week ending {until_l:%A, %d %B %Y} {until_l:%H:%M} {zone}")
    add("")
    add(f"Window: {since_l:%Y-%m-%d %H:%M} to {until_l:%Y-%m-%d %H:%M} ({zone})")
    add("")

    add("## Ingest")
    add("")
    arrow = "+" if r.delta >= 0 else ""
    add(
        f"- Articles ingested: **{r.ingested:,}** ({arrow}{r.delta:.1f}% vs prior week"
        f" — {r.ingested_prev:,})"
    )
    add(f"- Grouped into stories: {r.grouped:,} ({_pct(r.grouped, r.ingested)}% of ingest)")
    add(f"- Full text retrieved: {r.body_read:,} ({_pct(r.body_read, r.ingested)}%)")
    add(f"- New stories: {r.stories_week:,}")
    add("")

    if r.daily:
        peak = max(d.n for d in r.daily)
        add("Daily ingest:")
        add("")
        add("```")
        for d in r.daily:
            add(f"{d.day}  {d.n:>5}  {_bar(d.n, peak)}")
        add("```")
        add("")

    add("## Sources")
    add("")
    live, silent = len(r.sources_live), len(r.sources_silent)
    add(f"- Publishing this week: **{live}** of {live + silent} carried")
    if r.banned_publishers:
        add(f"- Not carried (operator ban): {r.banned_publishers}")
    if r.tiers:
        total = sum(t.n for t in r.tiers) or 1
        mix = ", ".join(f"{t.tier} {100.0 * t.n / total:.0f}%" for t in r.tiers)
        add(f"- Tier mix: {mix}")
    add("")
    if r.sources_live[:10]:
        add("| Source | Tier | Authority | Articles |")
        add("|---|---|---|---|")
        for s in r.sources_live[:10]:
            add(f"| {s.name} | {s.tier} | {s.authority:.2f} | {s.n:,} |")
        add("")

    if r.endpoints_dropped or r.endpoints_failing or r.sites_unconfigured:
        add("## Feed health")
        add("")
        if r.endpoints_dropped:
            add(
                f"**Dropped from the schedule ({len(r.endpoints_dropped)})** — at the"
                " failure ceiling, so nothing retries them:"
            )
            add("")
            for e in r.endpoints_dropped:
                st = f"HTTP {e.last_status}" if e.last_status else "no response"
                add(f"- {e.name} (authority {e.authority:.2f}) — {st}")
            add("")
        if r.endpoints_failing:
            add(f"**Failing ({len(r.endpoints_failing)})** — still retried:")
            add("")
            for e in r.endpoints_failing:
                st = f"HTTP {e.last_status}" if e.last_status else "no response"
                add(f"- {e.name} — {e.failure_streak}/10 failures, {st}")
            add("")
        if r.sites_unconfigured:
            add(
                f"**No feed configured ({len(r.sites_unconfigured)})** — registered as a"
                " source but with nothing to poll:"
            )
            add("")
            for s in r.sites_unconfigured:
                add(f"- {s.name} (authority {s.authority:.2f})")
            add("")

    add("## Pipeline")
    add("")
    if r.queue:
        add("| Stage | State | Jobs |")
        add("|---|---|---|")
        for q in r.queue:
            add(f"| {q.stage} | {q.state} | {q.n:,} |")
        add("")
    judged_pct = _pct(r.stories_judged, r.stories_total)
    add(f"- Stories judged: {r.stories_judged:,} of {r.stories_total:,} ({judged_pct}%)")
    if r.last_judged:
        stale = (datetime.now(UTC) - r.last_judged).days
        add(f"- Last judged: {r.last_judged:%Y-%m-%d} ({stale} days ago)")
    add(f"- Unjudged: **{r.unjudged:,}**")
    add("")

    add("## Delivery")
    add("")
    d = r.posts - r.posts_prev
    add(f"- Stories posted to Slack: **{r.posts:,}** ({'+' if d >= 0 else ''}{d} vs prior week)")
    add(
        f"- With a summary reply: {r.posts_with_summary:,} ({_pct(r.posts_with_summary, r.posts)}%)"
    )
    add(f"- Daily digests filed: {len(r.digests)} of 7")
    if r.digests:
        add("")
        for g in r.digests:
            add(f"  - {g.day}: {g.story_count} stories")
    add("")
    add(f"- Reader events: {r.events:,} from {r.users_active} active user(s)")
    add("")

    add("## Topics")
    add("")
    add("| Topic | Matches | Prior | Change | Avg score |")
    add("|---|---|---|---|---|")
    backfilled = False
    for t in r.topics:
        # A topic born inside either window has no comparable prior week: its
        # first pass matched the standing corpus, not that week's news.
        if t.created_at >= r.since - timedelta(days=7):
            chg, backfilled = "backfill*", True
        elif not t.n_prev:
            chg = "new"
        else:
            chg = f"{100.0 * (t.n - t.n_prev) / t.n_prev:+.0f}%"
        score = f"{t.score:.3f}" if t.score is not None else "—"
        add(f"| {t.title} | {t.n:,} | {t.n_prev:,} | {chg} | {score} |")
    add("")
    if backfilled:
        add(
            "_*Created inside the comparison window: the figure includes a one-off"
            " backfill against the standing corpus, so it is not a weekly rate._"
        )
        add("")

    add("## Most-covered stories")
    add("")
    if r.top:
        for i, s in enumerate(r.top, 1):
            reach = f" — {s.source_count} outlets" if s.source_count > 1 else ""
            add(f"{i}. {s.title} ({s.site}{reach})")
    else:
        add("_No stories cleared the content gates this week._")
    add("")
    if r.gated:
        add(f"_{r.gated} stor{'y' if r.gated == 1 else 'ies'} withheld by the content gates._")
        add("")

    return "\n".join(lines)


# ------------------------------------------------------------------ Slack


# Slack's mrkdwn has no table support: a markdown table renders as raw pipes.
# The columns still carry the meaning, so they are re-laid as fixed-width text
# inside a code block, which Slack renders in monospace and aligns.
def _fixed_table(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    out = ["```", "  ".join(h.ljust(widths[i]) for i, h in enumerate(header)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for r in rows:
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
    out.append("```")
    return out


def render_slack(r: Report) -> str:
    """The same week, laid out for a chat channel.

    Deliberately shorter than the markdown file: a channel post that has to be
    scrolled past every Saturday stops being read. The file keeps the full
    per-feed and per-source detail; this keeps what changes a decision.
    """
    zone = datetime.now(tz()).strftime("%Z") or settings().digest_timezone
    since_l, until_l = r.since.astimezone(tz()), r.until.astimezone(tz())
    out: list[str] = []
    add = out.append

    add(f"*TechTrend Weekly* — week ending {until_l:%A, %d %B %Y}")
    add(f"_{since_l:%d %b %H:%M} to {until_l:%d %b %H:%M} {zone}_")
    add("")

    arrow = "+" if r.delta >= 0 else ""
    add(f"*Ingest* `{r.ingested:,}` articles ({arrow}{r.delta:.1f}% vs prior week)")
    add(f"• {_pct(r.body_read, r.ingested)}% full text · {r.stories_week:,} new stories")
    add(f"*Delivery* `{r.posts:,}` stories posted · {len(r.digests)} of 7 digests")
    live, silent = len(r.sources_live), len(r.sources_silent)
    add(f"*Sources* `{live}` of {live + silent} publishing")
    add("")

    # The health lines are the reason an operator opens this at all, so they
    # lead rather than sit under the volume figures.
    alerts: list[str] = []
    if r.endpoints_dropped:
        alerts.append(
            f"`{len(r.endpoints_dropped)}` feeds past the retry ceiling — nothing retries them"
        )
    if r.endpoints_failing:
        worst = max(r.endpoints_failing, key=lambda e: e.failure_streak)
        alerts.append(
            f"`{len(r.endpoints_failing)}` feeds failing (worst: {worst.name}, "
            f"{worst.failure_streak}/10)"
        )
    if r.sites_unconfigured:
        names = ", ".join(s.name for s in r.sites_unconfigured[:4])
        alerts.append(f"`{len(r.sites_unconfigured)}` sources with no feed configured — {names}")
    if r.unjudged:
        stale = f", last ran {r.last_judged:%d %b}" if r.last_judged else ""
        alerts.append(f"`{r.unjudged:,}` stories unjudged{stale}")
    if alerts:
        add("*Needs attention*")
        for a in alerts:
            add(f"• {a}")
        add("")

    if r.topics:
        add("*Topics*")
        rows = []
        for t in r.topics[:8]:
            if t.created_at >= r.since - timedelta(days=7):
                chg = "backfill"
            elif not t.n_prev:
                chg = "new"
            else:
                chg = f"{100.0 * (t.n - t.n_prev) / t.n_prev:+.0f}%"
            rows.append([t.title[:34], f"{t.n:,}", chg])
        out.extend(_fixed_table(["Topic", "Matches", "vs prior"], rows))
        add("")

    if r.top:
        add("*Most-covered stories*")
        for i, s in enumerate(r.top[:5], 1):
            reach = f" · {s.source_count} outlets" if s.source_count > 1 else ""
            add(f"{i}. {s.title} _({s.site}{reach})_")
        add("")
    if r.gated:
        add(f"_{r.gated} withheld by the content gates._")

    return "\n".join(out).strip()


def slack_blocks(r: Report) -> tuple[str, list[dict[str, Any]]]:
    """(fallback, blocks). Fallback is the push-notification line."""
    until_l = r.until.astimezone(tz())
    heading = f"TechTrend Weekly — week ending {until_l:%d %B %Y}"
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading, "emoji": True}}
    ]
    # Slack rejects a section over 3000 chars, so the body is packed into as
    # many sections as it needs rather than truncated. Splits fall on blank
    # lines so a table never straddles two blocks.
    body = render_slack(r)
    parts: list[str] = []
    cur = ""
    for para in body.split("\n\n"):
        if cur and len(cur) + len(para) + 2 > 2900:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    for chunk in parts:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
    return heading, blocks
