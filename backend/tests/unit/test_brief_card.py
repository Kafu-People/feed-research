"""The channel card: short, checked, and always postable."""

from __future__ import annotations

from datetime import date

import pytest

from techtrend.deliver import brief_card as bc
from techtrend.deliver.brief import slack_problems

TODAY = date(2026, 11, 17)

REPORT = (
    "*NEW SINCE LAST WEEK*\n\n"
    "OpenAI raised critical-finding rewards fourfold on 2026-11-03 (SPREADING). "
    "Mercor lists 239 red-team roles at $55 to $165 an hour as of 2026-11-11 (EARLY).\n\n"
    "*OPEN PROGRAMS*\n\n"
    "Anthropic pays up to $35,000 per universal jailbreak through HackerOne. "
    "Gray Swan Arena runs recurring prize challenges for anyone."
)

GOOD = """Here you go: {"headline": "OpenAI quadrupled bug-bounty rewards",
 "points": ["OpenAI raised critical rewards 4x (2026-11-03)", "Mercor lists 239 roles"],
 "new": [{"text": "OpenAI rewards up 4x", "label": "spreading"}],
 "action": "Register for OpenAI's program on Bugcrowd"}"""


class _S:
    block_terms: tuple[str, ...] = ("tel aviv",)
    gemini_write_model = "m"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bc, "settings", lambda: _S())


def test_model_json_becomes_a_card() -> None:
    card = bc.parse(GOOD)
    assert card is not None
    assert card.headline == "OpenAI quadrupled bug-bounty rewards"
    assert len(card.points) == 2 and card.new[0].label == "SPREADING"


def test_long_fields_are_trimmed_and_lists_capped() -> None:
    raw = (
        '{"headline": "' + "h" * 300 + '", "points": ["' + '", "'.join(["p" * 400] * 6) + '"],'
        ' "new": [], "action": "' + "a" * 500 + '"}'
    )
    card = bc.parse(raw)
    assert card is not None
    assert len(card.headline) <= bc.HEADLINE_MAX and card.headline.endswith("…")
    assert len(card.points) == 3 and all(len(p) <= bc.POINT_MAX for p in card.points)
    assert len(card.action) <= bc.ACTION_MAX


@pytest.mark.parametrize("raw", ["", "no json here", "{not json}", '{"points": []}'])
def test_unusable_output_is_rejected(raw: str) -> None:
    assert bc.parse(raw) is None


def test_the_fallback_is_built_from_the_reports_own_sentences() -> None:
    card = bc.fallback(REPORT)
    assert not card.generated
    assert card.headline.startswith("OpenAI raised critical-finding rewards")
    assert any("Mercor" in p for p in card.points)
    assert all(p in REPORT.replace("*", "") or p.endswith("…") for p in card.points)


@pytest.mark.asyncio
async def test_a_card_that_asks_a_question_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    async def write(system, user, *, model=None):
        return ('{"headline": "Should I expand the report?", "points": []}', 1, 1)

    monkeypatch.setattr(bc.gemini, "write", write)
    card = await bc.summarize(REPORT, TODAY)
    assert not card.generated and "?" not in card.headline


@pytest.mark.asyncio
async def test_a_blocked_term_in_the_card_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    async def write(system, user, *, model=None):
        return ('{"headline": "Workers in Tel Aviv report higher pay", "points": []}', 1, 1)

    monkeypatch.setattr(bc.gemini, "write", write)
    card = await bc.summarize(REPORT, TODAY)
    assert "Tel Aviv" not in card.headline


@pytest.mark.asyncio
async def test_a_failed_model_call_still_gives_a_card(monkeypatch: pytest.MonkeyPatch) -> None:
    async def write(system, user, *, model=None):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(bc.gemini, "write", write)
    card = await bc.summarize(REPORT, TODAY)
    assert card.headline and not card.generated


@pytest.mark.asyncio
async def test_the_model_is_given_only_the_report_and_the_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    async def write(system, user, *, model=None):
        seen["user"] = user
        return (GOOD, 1, 1)

    monkeypatch.setattr(bc.gemini, "write", write)
    card = await bc.summarize(REPORT, TODAY)
    assert card.generated
    assert seen["user"].startswith("Today's date is 2026-11-17.") and REPORT in seen["user"]


def _render(card: bc.Card, flags: list[str] | None = None) -> str:
    _, blocks = bc.card_blocks(
        card, title="redteam", today=TODAY, searches=8, source_count=69, flags=flags or []
    )
    assert slack_problems(blocks) == []
    return "\n".join(b["text"]["text"] if "text" in b else b["elements"][0]["text"] for b in blocks)


def test_the_card_is_short_and_points_to_the_thread() -> None:
    card = bc.parse(GOOD)
    assert card is not None
    out = _render(card)
    assert out.startswith("📊 redteam — Tue Nov 17")
    assert "*OpenAI quadrupled bug-bounty rewards*" in out
    assert "`SPREADING`" in out and "👉 *Today:*" in out
    assert "8 searches · 69 sources · full report and tables in the thread" in out
    assert len(out.splitlines()) <= 14


def test_a_quiet_day_says_so_in_one_line() -> None:
    out = _render(bc.Card(headline="Pay held steady", points=["Rates unchanged (2026-11-16)"]))
    assert bc.QUIET in out and "New this week" not in out


def test_labels_sit_on_the_card() -> None:
    out = _render(bc.Card(headline="h"), flags=["*UNVERIFIED (no sources)*"])
    assert "*UNVERIFIED (no sources)*" in out.splitlines()[1]


def test_card_text_is_escaped_for_slack() -> None:
    out = _render(bc.Card(headline="R&D <rates> up"))
    assert "R&amp;D &lt;rates&gt; up" in out


def test_old_items_do_not_appear_as_new() -> None:
    """The 2026-11-17 dry run listed a March acquisition under New this week."""
    card = bc.Card(
        headline="h",
        new=[
            bc.NewItem("OpenAI acquired Promptfoo (2026-03-09)", "CROWDED"),
            bc.NewItem("Mercor opened 239 roles (2026-11-11)", "EARLY"),
            bc.NewItem("A new waitlist opened", "EARLY"),
        ],
    )
    kept = [n.text for n in bc.only_recent(card, TODAY).new]
    assert kept == ["Mercor opened 239 roles (2026-11-11)", "A new waitlist opened"]
