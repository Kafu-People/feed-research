"""The jobwatch stage: what AI-data vendors started hiring for today.

The earliest public sign of a new earning opportunity is not a Reddit thread
or an article -- it is the vendor opening the role. "AI Conversation Recording
Contributor - Catalan" is on RWS's job board days before anyone writes about
it. So once a day this reads the public job boards of the vendors that run AI
training work and posts only what is NEW, filtered to the roles a contributor
could take: trainers, raters, annotators, contributors, experts.

Read-only, no model, no search: three public JSON APIs (Greenhouse, Lever,
Ashby), fetched through `PoliteFetcher` so robots.txt and the per-host limits
apply exactly as they do to the crawler.

The first time a board is seen, everything on it is recorded and nothing is
posted. Otherwise the first run would announce 169 Scale AI roles as "new".
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from techtrend.deliver.brief import _chunk
from techtrend.deliver.slack import Block, SlackClient
from techtrend.platform import queue, telemetry
from techtrend.platform.config import settings
from techtrend.platform.db import session_scope
from techtrend.shared.collect.fetcher import PoliteFetcher


@dataclass(frozen=True)
class Board:
    company: str
    ats: str  # greenhouse | lever | ashby
    token: str

    @property
    def key(self) -> str:
        return f"{self.ats}:{self.token}"

    @property
    def url(self) -> str:
        return {
            "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{self.token}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{self.token}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{self.token}",
        }[self.ats]


@dataclass(frozen=True)
class Posting:
    ext_id: str
    title: str
    location: str
    url: str


# Probed 2026-11-12: each board answered with listings. Left out: Surge AI,
# micro1, Alignerr, DataAnnotation, Outlier and Anyone AI (no public board on
# any of the three systems), "greenlight" on Lever (Greenlight the children's
# debit-card company, not the AI-trainer recruiter), "invisible" on Greenhouse
# (five umbrella "Opportunities at Invisible" posts; "invisibletech" is the
# real board), Handshake on Greenhouse (empty; its board moved to Ashby).
WATCH: list[Board] = [
    Board("Scale AI / Outlier", "greenhouse", "scaleai"),
    Board("Labelbox / Alignerr", "greenhouse", "labelbox"),
    Board("Turing", "greenhouse", "turing"),
    Board("Invisible Technologies", "greenhouse", "invisibletech"),
    Board("Snorkel AI", "greenhouse", "snorkelai"),
    Board("Prolific", "greenhouse", "prolific"),
    Board("Toloka", "greenhouse", "toloka"),
    Board("Mercor", "ashby", "mercor"),
    Board("Handshake AI", "ashby", "handshake"),
    Board("Appen", "lever", "appen"),
    Board("RWS TrainAI", "lever", "rws"),
]

# Roles a contributor could take, not the vendor's own staff. Word-start
# matches: "annotat" catches annotator and annotation. Deliberately absent:
# a bare "data" (Data Scientist, Director of Data) and "contract" (Contracts
# Manager) -- both are staff roles on every board probed.
_RELEVANT = re.compile(
    r"\b(ai trainer|trainer|tutor|annotat|label(?:l)?er|labeling|rater|rating|evaluator"
    r"|contributor|expert|freelance|contractor|linguist|transcri|red team|rlhf"
    r"|talent pool|domain specialist|subject matter|ai training|data specialist|reviewer)",
    re.IGNORECASE,
)
# Staff roles that mention contributors or experts: "Contributor Experience
# Manager", "Domain Expert Recruiter (Contractor)", "Senior Software Engineer,
# Annotations" (seen in the 2026-11-12 baseline). A freelance title overrides
# this -- "Freelance Senior DevSecOps Engineer" is a gig someone can take.
_STAFF = re.compile(r"\b(recruit|director|head of|vice president|manager|software engineer,)", re.I)
_GIG = re.compile(r"\bfreelance\b", re.I)


def relevant(title: str) -> bool:
    if not _RELEVANT.search(title):
        return False
    return bool(_GIG.search(title)) or not _STAFF.search(title)


def parse(ats: str, payload: Any) -> list[Posting]:
    """A board's JSON in, postings out. Unknown shapes give an empty list."""
    out: list[Posting] = []
    if ats == "greenhouse":
        for j in (payload or {}).get("jobs") or []:
            loc = (j.get("location") or {}).get("name") or ""
            out.append(Posting(str(j["id"]), j.get("title", ""), loc, j.get("absolute_url", "")))
    elif ats == "lever":
        for j in payload or []:
            loc = (j.get("categories") or {}).get("location") or ""
            out.append(Posting(str(j["id"]), j.get("text", ""), loc, j.get("hostedUrl", "")))
    elif ats == "ashby":
        for j in (payload or {}).get("jobs") or []:
            if j.get("isListed") is False:
                continue
            loc = j.get("location") or ""
            if j.get("isRemote"):
                loc = f"{loc} (remote)" if loc else "Remote"
            out.append(Posting(str(j["id"]), j.get("title", ""), loc, j.get("jobUrl", "")))
    return [p for p in out if p.title and p.url]


def diff(known: dict[str, bool], current: list[Posting]) -> tuple[list[Posting], list[str]]:
    """(new postings, ext_ids now gone). `known` maps ext_id -> still open.

    A posting that went away and came back is not new: vendors close and
    reopen the same evergreen role, and announcing it each time is noise.
    """
    now = {p.ext_id for p in current}
    new = [p for p in current if p.ext_id not in known]
    gone = [ext for ext, open_ in known.items() if open_ and ext not in now]
    return new, gone


async def _fetch(fetcher: PoliteFetcher, board: Board) -> list[Posting]:
    res = await fetcher.get(board.url)
    if res.status != 200:
        raise RuntimeError(f"{board.key} answered {res.status}")
    return parse(board.ats, json.loads(res.body))


_KNOWN = text("SELECT ext_id, gone_at IS NULL FROM job_postings WHERE board = :b")
_INSERT = text("""
    INSERT INTO job_postings (board, ext_id, company, title, location, url)
    VALUES (:board, :ext_id, :company, :title, :location, :url)
    ON CONFLICT (board, ext_id) DO NOTHING
""")
_REOPEN = text(
    "UPDATE job_postings SET gone_at = NULL"
    " WHERE board = :b AND gone_at IS NOT NULL AND ext_id = ANY(:ids)"
)
_GONE = text("UPDATE job_postings SET gone_at = now() WHERE board = :b AND ext_id = ANY(:ids)")


async def _sync(board: Board, current: list[Posting]) -> list[Posting]:
    """Record what the board lists now; return what is new since last time.

    Returns nothing on a board's first run -- that run is the baseline.
    """
    async with session_scope() as s:
        known = {r[0]: bool(r[1]) for r in (await s.execute(_KNOWN, {"b": board.key})).all()}
        new, gone = diff(known, current)
        for p in new:
            await s.execute(
                _INSERT,
                {
                    "board": board.key,
                    "ext_id": p.ext_id,
                    "company": board.company,
                    "title": p.title,
                    "location": p.location,
                    "url": p.url,
                },
            )
        if gone:
            await s.execute(_GONE, {"b": board.key, "ids": gone})
        await s.execute(_REOPEN, {"b": board.key, "ids": [p.ext_id for p in current]})
    if not known:
        telemetry.log.info("jobwatch.baseline", board=board.key, postings=len(current))
        return []
    return new


def render(new: dict[str, list[Posting]]) -> tuple[str, list[Block]]:
    """One message: a section per company, each role a linked line."""
    total = sum(len(v) for v in new.values())
    heading = f"AI-data vendor job boards — {total} new role{'s' if total != 1 else ''}"
    lines: list[str] = []
    for company in sorted(new):
        lines.append(f"*{company}*")
        for p in sorted(new[company], key=lambda p: p.title):
            title = p.title.replace("|", "❘").replace(">", "&gt;").replace("<", "&lt;")
            where = f" — {p.location}" if p.location else ""
            lines.append(f"• <{p.url}|{title}>{where}")
        lines.append("")
    blocks: list[Block] = [
        {"type": "header", "text": {"type": "plain_text", "text": heading[:150], "emoji": True}},
        *[
            {"type": "section", "text": {"type": "mrkdwn", "text": piece}}
            for piece in _chunk("\n".join(lines).strip(), 2900)
        ],
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Contributor roles only (trainer, rater, annotator, expert…). "
                    "First seen today on the vendor's public job board._",
                }
            ],
        },
    ]
    return heading, blocks[:50]


async def run(job: queue.Job) -> None:
    channel = settings().slack_brief_channel
    if not channel:
        return
    fetcher = PoliteFetcher()
    found: dict[str, list[Posting]] = defaultdict(list)
    try:
        for board in WATCH:
            # One board failing -- moved, renamed, rate-limited -- is that
            # board's problem; the rest still report. Nothing is marked gone
            # for a board that did not answer.
            try:
                current = await _fetch(fetcher, board)
            except Exception:  # noqa: BLE001 - one board, not the watch
                telemetry.log.warning("jobwatch.board_failed", board=board.key, exc_info=True)
                continue
            new = [p for p in await _sync(board, current) if relevant(p.title)]
            found[board.company] += new
    finally:
        await fetcher.aclose()

    found = {k: v for k, v in found.items() if v}
    telemetry.log.info("jobwatch.done", new=sum(len(v) for v in found.values()))
    if not found:
        return
    fallback, blocks = render(found)
    await SlackClient().post(channel, fallback, blocks=blocks, unfurl=False)
