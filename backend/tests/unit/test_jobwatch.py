"""The jobwatch stage: parse three job-board shapes, keep contributor roles,
announce only what is new, and never let one board stop the others."""

from __future__ import annotations

from typing import Any

import pytest

from techtrend.deliver import jobwatch
from techtrend.deliver.jobwatch import Board, Posting, diff, parse, relevant, render

# ------------------------------------------------------------------ parsing


def test_parse_greenhouse() -> None:
    payload = {
        "jobs": [
            {
                "id": 47,
                "title": "AI Trainer - Rust",
                "location": {"name": "Remote"},
                "absolute_url": "https://job-boards.greenhouse.io/scaleai/jobs/47",
            }
        ]
    }
    assert parse("greenhouse", payload) == [
        Posting(
            "47", "AI Trainer - Rust", "Remote", "https://job-boards.greenhouse.io/scaleai/jobs/47"
        )
    ]


def test_parse_lever() -> None:
    payload = [
        {
            "id": "af96",
            "text": "AI Conversation Recording Contributor - Catalan",
            "categories": {"location": "Barcelona"},
            "hostedUrl": "https://jobs.lever.co/rws/af96",
        }
    ]
    (p,) = parse("lever", payload)
    assert (p.ext_id, p.location) == ("af96", "Barcelona")


def test_parse_ashby_marks_remote_and_skips_unlisted() -> None:
    payload = {
        "jobs": [
            {
                "id": "1",
                "title": "Expert Evaluator",
                "location": "New York",
                "isRemote": True,
                "jobUrl": "https://jobs.ashbyhq.com/mercor/1",
            },
            {
                "id": "2",
                "title": "Hidden",
                "location": "",
                "isListed": False,
                "jobUrl": "https://jobs.ashbyhq.com/mercor/2",
            },
        ]
    }
    assert parse("ashby", payload) == [
        Posting("1", "Expert Evaluator", "New York (remote)", "https://jobs.ashbyhq.com/mercor/1")
    ]


def test_parse_survives_an_unexpected_shape() -> None:
    assert parse("greenhouse", {"error": "nope"}) == []
    assert parse("lever", None) == []


# ---------------------------------------------------------------- relevance


@pytest.mark.parametrize(
    "title",
    [
        "AI Trainer - Rust",
        "Freelance Mathematics Expert",
        "AI Conversation Recording Contributor - Catalan",
        "Data Annotator (Portuguese)",
        "Search Quality Rater",
        "*Future Opportunities: Join our global TrainAI talent pool",
        "Freelance Senior DevSecOps Engineer",
        "Freelance AI Data Project Manager",
        "AI Red Teamer, Cybersecurity (Remote)",
    ],
)
def test_contributor_roles_are_kept(title: str) -> None:
    assert relevant(title)


@pytest.mark.parametrize(
    "title",
    [
        "Contributor Experience Manager, Community",
        "Global Specialized Domain Expert Recruiter (Contractor)",
        "Senior Software Engineer, Annotations",
        "Data Scientist (Forward Deployed)",
        "Contracts Manager",
        "Account Executive",
        "Product Manager",
    ],
)
def test_staff_roles_are_ignored(title: str) -> None:
    """Seen on the real boards: these are the vendor's own staff."""
    assert not relevant(title)


# --------------------------------------------------------------------- diff


def _p(ext: str, title: str = "AI Trainer") -> Posting:
    return Posting(ext, title, "", f"https://x/{ext}")


def test_diff_reports_new_and_gone() -> None:
    new, gone = diff({"a": True, "b": True}, [_p("a"), _p("c")])
    assert [p.ext_id for p in new] == ["c"]
    assert gone == ["b"]


def test_a_reopened_role_is_not_new() -> None:
    """Vendors close and reopen the same evergreen role; that is not news."""
    new, gone = diff({"a": False}, [_p("a")])
    assert new == [] and gone == []


# ---------------------------------------------------------------------- run


class _Spy:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def post(self, channel: str, text: str, **kw: Any) -> None:
        self.posts.append({"channel": channel, "text": text, **kw})


class _Fetcher:
    async def aclose(self) -> None:
        return None


def _install(monkeypatch: pytest.MonkeyPatch, boards, fetch, sync) -> _Spy:
    spy = _Spy()

    class _S:  # settings() is cached; an env var set here would be ignored
        slack_brief_channel = "C0BRIEFS001"

    monkeypatch.setattr(jobwatch, "settings", lambda: _S())
    monkeypatch.setattr(jobwatch, "WATCH", boards)
    monkeypatch.setattr(jobwatch, "PoliteFetcher", _Fetcher)
    monkeypatch.setattr(jobwatch, "_fetch", fetch)
    monkeypatch.setattr(jobwatch, "_sync", sync)
    monkeypatch.setattr(jobwatch, "SlackClient", lambda: spy)
    return spy


@pytest.mark.asyncio
async def test_new_contributor_roles_are_posted_and_staff_roles_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = Board("RWS TrainAI", "lever", "rws")

    async def fetch(_f, _b):
        return [_p("1", "Contributor - Catalan"), _p("2", "Account Executive")]

    async def sync(_b, current):
        return current

    spy = _install(monkeypatch, [board], fetch, sync)
    await jobwatch.run(None)  # type: ignore[arg-type]
    (post,) = spy.posts
    body = str(post["blocks"])
    assert "Contributor - Catalan" in body and "Account Executive" not in body
    assert post["channel"] == "C0BRIEFS001" and post["unfurl"] is False


@pytest.mark.asyncio
async def test_nothing_new_posts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch(_f, _b):
        return [_p("1")]

    async def sync(_b, _c):
        return []  # baseline run, or nothing changed

    spy = _install(monkeypatch, [Board("X", "greenhouse", "x")], fetch, sync)
    await jobwatch.run(None)  # type: ignore[arg-type]
    assert spy.posts == []


@pytest.mark.asyncio
async def test_one_failing_board_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    broken, fine = Board("Broken", "greenhouse", "gone"), Board("Fine", "lever", "ok")
    synced: list[str] = []

    async def fetch(_f, b):
        if b is broken:
            raise RuntimeError("404")
        return [_p("9", "Expert Rater")]

    async def sync(b, current):
        synced.append(b.key)
        return current

    spy = _install(monkeypatch, [broken, fine], fetch, sync)
    await jobwatch.run(None)  # type: ignore[arg-type]
    # The broken board is never synced, so nothing on it is marked gone.
    assert synced == ["lever:ok"]
    assert "Expert Rater" in str(spy.posts[0]["blocks"])


def test_render_groups_by_company() -> None:
    heading, blocks = render(
        {"B Co": [_p("1", "Rater")], "A Co": [_p("2", "Tutor"), _p("3", "AI Trainer")]}
    )
    assert heading.endswith("3 new roles")
    text = blocks[1]["text"]["text"]
    assert text.index("*A Co*") < text.index("*B Co*")
