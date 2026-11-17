"""The checks a brief passes before posting, each on the shape that went wrong
in #feed-research-briefs in November 2026."""

from __future__ import annotations

from datetime import date

import pytest

from techtrend.ai.gemini import TABLES_MARKER, Brief, Source
from techtrend.deliver import brief as brief_mod
from techtrend.deliver import brief_quality as q

TODAY = date(2026, 11, 17)

# --------------------------------------------------------------- questions

DATAANNOTATION_NOV16 = (
    "*What I found and what I cannot find:*\n\n"
    "• *Projects/codenames*: I found no current project codenames\n\n"
    "Given these gaps I cannot ethically produce the full two-part report.\n\n"
    "*My recommendation:* This report requires either:\n"
    "1. A narrower scope\n2. Acceptance that sections 5 and 6 will need a note\n"
    "3. Additional time for me to source these details. Which would you prefer?"
)


@pytest.mark.parametrize(
    "text",
    [
        DATAANNOTATION_NOV16,
        "Full report here.\n\nWould you like me to expand section 3?",
        "Report.\n\n*Should I proceed?*",
        "Report text. Let me know if you want the tables.",
    ],
)
def test_questions_to_the_reader_are_caught(text: str) -> None:
    assert q.asks_reader(text)


def test_a_report_that_mentions_a_question_is_not_flagged() -> None:
    text = 'Workers ask "is it legit?" on Reddit.\n\nPay held at **$40/hr**.'
    assert not q.asks_reader(text)


def test_only_a_question_is_never_postable() -> None:
    assert q.only_question(DATAANNOTATION_NOV16)
    long_report = "Paragraph of findings. " * 200 + "\n\nShould I add more?"
    assert not q.only_question(long_report)  # incomplete, but it is a report


# ------------------------------------------------------------------- dates


def test_relative_dates_become_absolute() -> None:
    out, n = q.absolutize_relative_dates(
        "Reviews (637 days ago). Posted 3 days ago. Seen a week ago. Rates (recent).", TODAY
    )
    assert "2025-02-18" in out and "2026-11-14" in out and "2026-11-10" in out
    assert "(date unknown)" in out and "ago" not in out
    assert n == 4


def test_months_ago_names_only_the_month() -> None:
    out, _ = q.absolutize_relative_dates("Raised funds 3 months ago.", TODAY)
    assert "about 2026-08" in out


def test_dates_are_found_in_every_common_form() -> None:
    found = q.find_dates("on 2026-11-02, November 3, 2026, and 4 Nov 2026")
    assert found == [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]


# ----------------------------------------------------------------- expired


def test_a_past_deadline_sentence_is_removed_and_logged() -> None:
    text = (
        "Gray Swan's IPI Black challenge had $300,000 in prizes, closing on November 2, 2026. "
        "Gray Swan Arena runs recurring challenges."
    )
    out, removed = q.drop_expired(text, TODAY)
    assert "closing on November 2" not in out
    assert "recurring challenges" in out
    assert len(removed) == 1


def test_closed_rows_and_past_deadline_rows_leave_the_table() -> None:
    table = "\n".join(
        [
            "| Program | Deadline | Status |",
            "|---|---|---|",
            "| Gray Swan IPI | 2026-11-02 | Closed |",
            "| HackAPrompt | deadline 2026-10-01 | Open |",
            "| Bugcrowd OpenAI | rolling | Open |",
        ]
    )
    out, removed = q.drop_expired(table, TODAY)
    assert "Bugcrowd OpenAI" in out and "|---|" in out
    assert "Gray Swan IPI" not in out and "HackAPrompt" not in out
    assert len(removed) == 2


@pytest.mark.parametrize(
    "keep",
    [
        # All removed by the first version in the 2026-11-17 dry run. None is
        # an expired program: the past date is not the deadline's date.
        "On 2026-11-03, OpenAI announced it was more than quadrupling its rewards "
        "for critical findings through its bug bounty program.",
        "Qwen4-Max preview opened on 2026-11-11 with a time limit through 2026-11-25.",
        "Total tech layoffs through May 2026 reached 128,270 (Full Scale, 2026-11-05).",
        "Scale AI cuts 14% staff and ends 500 contractor relationships (2026-11-14).",
        "Open signup through Mindrift: the page redirected when read on Sep 25, 2026.",
    ],
)
def test_a_past_date_that_is_not_a_deadline_stays(keep: str) -> None:
    out, removed = q.drop_expired(keep, TODAY)
    assert out == keep and removed == []


@pytest.mark.parametrize(
    "gone",
    [
        "The private program keeps GPT-5.5 in scope through 2026-07-27.",
        "Testing started 2026-04-28 and ran until 2026-07-27.",
        "Gray Swan Arena (deadline 2026-11-05) is the highest-visibility program.",
    ],
)
def test_an_attached_past_deadline_goes(gone: str) -> None:
    out, removed = q.drop_expired(gone, TODAY)
    assert out == "" and removed == [gone]


def test_a_row_marked_closed_after_its_dates_goes_even_if_open_to_all() -> None:
    """From the 2026-11-17 redteam dry run: 'Open, anonymous' is who may
    enter, '(closed)' is whether you still can."""
    table = (
        "| Competition | Sponsors | Prize | Dates | Who |\n|---|---|---|---|---|\n"
        "| Gray Swan IPI Black | Anthropic, Meta | $300,000 | 15 Oct – 5 Nov 2026 (closed) "
        "| Open, anonymous |\n"
        "| HackAPrompt 3.0 | Learn Prompting | $100,000 | rolling | Open |"
    )
    out, removed = q.drop_expired(table, TODAY)
    assert "IPI Black" not in out and "HackAPrompt" in out and len(removed) == 1


def test_a_deadline_without_a_year_is_read_as_this_year() -> None:
    gone = "0DIN offers a temporary $5,000 bounty from now through September 16th."
    out, removed = q.drop_expired(gone, TODAY)
    assert out == "" and removed == [gone]
    later = "A new cohort opens and applications close December 5th."
    assert q.drop_expired(later, TODAY) == (later, [])


def test_the_models_own_rules_do_not_double_the_dividers() -> None:
    body = "*A*\n\nOne.\n\n---\n\n*B*\n\nTwo."
    (_, blocks), *_ = brief_mod._render_parts("x", body, [], 1)
    texts = [b["text"]["text"] for b in blocks if b["type"] == "section"]
    assert not any(t.strip() == "---" or "\n---" in t for t in texts)
    assert [b["type"] for b in blocks].count("divider") == 1


def test_an_open_program_row_stays_when_one_challenge_ended() -> None:
    table = (
        "| Program | Run By | Status |\n|---|---|---|\n"
        "| Gray Swan Arena | Gray Swan | Open (IPI Black through 2026-11-05) |"
    )
    out, removed = q.drop_expired(table, TODAY)
    assert "Gray Swan Arena" in out and removed == []


def test_a_future_deadline_stays() -> None:
    text = "Applications close on 2026-12-01 for the new red-team cohort."
    out, removed = q.drop_expired(text, TODAY)
    assert out == text and removed == []


# --------------------------------------------- tables and message length


def _redteam_like_table(rows: int = 40) -> str:
    """The shape of the Nov 16 redteam tables half: seven columns, long cells."""
    head = "| Program | Run By | Focus | Pay or Prize | Who Can Apply | Status | Link |"
    rule = "|---------|--------|-------|--------------|---------------|--------|------|"
    body = [
        f"| Program {i} with a long descriptive name | Lab {i} & partners | "
        "jailbreaks, prompt injection, agent misuse and adversarial prompts | "
        f"${i}000 per finding up to $100,000 | anyone worldwide, no credentials | "
        f"Open (rolling) | https://example.com/programs/{i}/apply-now |"
        for i in range(rows)
    ]
    return "## Open Red-Teaming and Bug Bounty Programs\n\n" + "\n".join([head, rule, *body])


def test_the_nov16_redteam_table_renders_within_slack_limits() -> None:
    """Reproduces the post that showed one line of raw markdown: its first
    section was stored at 3,126 characters, over Slack's 3,000."""
    messages = brief_mod._render_parts("redteam", _redteam_like_table(), [], 8, label="tables")
    for _, blocks in messages:
        assert brief_mod.slack_problems(blocks) == []
    sections = [b["text"]["text"] for _, bl in messages for b in bl if b["type"] == "section"]
    # The heading comes BEFORE the table, not after a piece of it.
    assert sections[0].startswith("*Open Red-Teaming and Bug Bounty Programs*")
    # Every piece of the table is inside a code block.
    assert all(s.count("```") % 2 == 0 for s in sections)
    assert not any(s.lstrip().startswith("|") for s in sections)
    # Nothing was dropped: every row is somewhere in the output.
    joined = "\n".join(sections)
    assert all(f"Program {i} " in joined for i in range(40))


def test_a_very_long_half_is_split_into_numbered_messages() -> None:
    long_body = "\n\n".join(f"## Section {i}\n\n" + ("Fact. " * 300) for i in range(60))
    messages = brief_mod._render_parts("aigigwork", long_body, [], 8, label="today")
    assert len(messages) >= 2
    headers = [bl[0]["text"]["text"] for _, bl in messages]
    assert headers[0].endswith(f"(1/{len(messages)})")
    assert headers[-1].endswith(f"({len(messages)}/{len(messages)})")
    for _, blocks in messages:
        assert brief_mod.slack_problems(blocks) == []
    joined = "".join(str(bl) for _, bl in messages)
    assert all(f"Section {i}*" in joined for i in range(60))


def test_slack_len_counts_entities_but_not_links() -> None:
    assert brief_mod.slack_len("a & b") == len("a & b") + 4
    assert brief_mod.slack_len("<https://x.com/a&b|t>") == len("<https://x.com/a&b|t>") + 4


# ----------------------------------------------------- posting end to end


class _Spy:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, channel, text_, blocks=None, thread_ts=None, unfurl=True):
        self.posts.append({"text": text_, "blocks": blocks or [], "thread_ts": thread_ts})
        return "1.0"


def _wire(monkeypatch: pytest.MonkeyPatch, answers: list[Brief]) -> tuple[_Spy, list[str]]:
    import contextlib

    calls: list[str] = []

    async def fake_research(prompt: str) -> Brief:
        calls.append(prompt)
        return answers[min(len(calls), len(answers)) - 1]

    class _Session:
        async def execute(self, *_a, **_kw):
            return None

    @contextlib.asynccontextmanager
    async def fake_scope():
        yield _Session()

    async def fake_claim(name):
        return None

    async def fake_release(name, prev):
        return None

    class _S:
        gemini_api_key = "k"
        slack_brief_channel = "C0BRIEFS001"
        block_terms: tuple[str, ...] = ()
        blocked_sites: tuple[str, ...] = ()
        brief_timezone = "America/New_York"

    spy = _Spy()
    monkeypatch.setattr(brief_mod.gemini, "research", fake_research)
    monkeypatch.setattr(brief_mod, "session_scope", fake_scope)
    monkeypatch.setattr(brief_mod, "_claim", fake_claim)
    monkeypatch.setattr(brief_mod, "_release", fake_release)
    monkeypatch.setattr(brief_mod, "settings", lambda: _S())
    monkeypatch.setattr(q, "settings", lambda: _S())
    monkeypatch.setattr(brief_mod.brief_card, "settings", lambda: _S())

    async def fake_summarize(report, today, *, name=""):
        return brief_mod.brief_card.fallback(report)  # no model call in a unit test

    monkeypatch.setattr(brief_mod.brief_card, "summarize", fake_summarize)
    return spy, calls


def _text(spy: _Spy) -> str:
    return "\n".join(str(p["blocks"]) for p in spy.posts)


REPORT = f"A full report on pay.\n{TABLES_MARKER}\n| Platform | Pay |\n|---|---|\n| A | $40 |"
SRC = [Source("reddit.com", "https://r/1"), Source("hiringlab.org", "https://h/1")]


@pytest.mark.asyncio
async def test_every_footer_shows_the_real_source_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """The write-up said "8 searches · 0 sources" while the log said 65: the
    count rode only on the last post, with the links."""
    spy, _ = _wire(monkeypatch, [Brief(text=REPORT, sources=SRC, queries=["a", "b"])])
    await brief_mod._one(spy, "aigigwork", "p")
    assert len(spy.posts) == 3  # card, then write-up and tables in its thread
    for p in spy.posts:
        assert "2 searches · 2 sources" in str(p["blocks"])
    assert "UNVERIFIED" not in _text(spy)


@pytest.mark.asyncio
async def test_zero_sources_is_labelled_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    spy, _ = _wire(monkeypatch, [Brief(text=REPORT, sources=[], queries=["a"])])
    await brief_mod._one(spy, "aigigwork", "p")
    first_section = next(b for b in spy.posts[0]["blocks"] if b["type"] == "section")
    assert first_section["text"]["text"].startswith("*UNVERIFIED (no sources)*")


@pytest.mark.asyncio
async def test_a_question_is_regenerated_once(monkeypatch: pytest.MonkeyPatch) -> None:
    spy, calls = _wire(
        monkeypatch,
        [
            Brief(text=DATAANNOTATION_NOV16, sources=SRC, queries=["a"]),
            Brief(text=REPORT, sources=SRC, queries=["b"]),
        ],
    )
    spent = await brief_mod._one(spy, "dataannotation", "p")
    assert len(calls) == 2 and spent == 2
    assert "Incomplete" not in _text(spy)
    assert "which would you prefer" not in _text(spy).lower()


@pytest.mark.asyncio
async def test_a_question_twice_is_never_posted(monkeypatch: pytest.MonkeyPatch) -> None:
    ask = Brief(text=DATAANNOTATION_NOV16, sources=SRC, queries=["a"])
    spy, calls = _wire(monkeypatch, [ask, ask])
    await brief_mod._one(spy, "dataannotation", "p")
    assert len(calls) == 2 and spy.posts == []


@pytest.mark.asyncio
async def test_a_long_report_that_still_asks_is_posted_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_ask = Brief(text="Findings. " * 400 + "\n\nWould you like more detail?", sources=SRC)
    spy, _ = _wire(monkeypatch, [long_ask, long_ask])
    await brief_mod._one(spy, "aigigwork", "p")
    first_section = next(b for b in spy.posts[0]["blocks"] if b["type"] == "section")
    assert "*Incomplete*" in first_section["text"]["text"]


@pytest.mark.asyncio
async def test_expired_items_and_relative_dates_are_fixed_before_posting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (
        "The IPI challenge closed on 2026-11-02 with $300,000 in prizes. "
        "Outlier pays weekly (637 days ago).\n"
        f"{TABLES_MARKER}\n| Program | Status |\n|---|---|\n| IPI | Closed |\n| Arena | Open |"
    )
    spy, _ = _wire(monkeypatch, [Brief(text=text, sources=SRC, queries=["a"])])
    monkeypatch.setattr(q, "today_local", lambda now=None: TODAY)
    await brief_mod._one(spy, "redteam", "p")
    out = _text(spy)
    assert "$300,000" not in out and "IPI" not in out
    assert "Arena" in out and "2025-02-18" in out and "days ago" not in out


@pytest.mark.asyncio
async def test_dry_run_writes_files_and_posts_nothing(tmp_path, monkeypatch) -> None:
    spy, _ = _wire(monkeypatch, [Brief(text=REPORT, sources=SRC, queries=["a"])])
    client = brief_mod.DryRunClient(tmp_path)
    claimed: list[str] = []

    async def no_claim(name):
        claimed.append(name)
        return None

    monkeypatch.setattr(brief_mod, "_claim", no_claim)
    await brief_mod._one(client, "aigigwork", "p")
    assert claimed == []  # a dry run never uses up the topic's daily slot
    assert len(client.posts) == 3 and spy.posts == []
    assert [p["thread_ts"] for p in client.posts] == [None, "dry.1", "dry.1"]
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".md") == [
        "01-channel.md",
        "02-thread.md",
        "03-thread.md",
    ]
