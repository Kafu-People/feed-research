"""M3 matcher units. The exit criterion test lives here: a perfect-scoring
excluded story still returns 0.0 -- gates are gates, not penalties."""

from __future__ import annotations

from techtrend.platform.config import DEFAULT_BLOCK_SITES, DEFAULT_BLOCK_TERMS, site_blocked
from techtrend.topic.match import StoryText, blocked, evaluate, searchable


def _story(text: str, embedding: list[float] | None = None) -> StoryText:
    st = searchable(text, None, [])
    return StoryText(text=st.text, embedding=embedding)


def _eval(story: StoryText, **kw: object):
    base: dict = dict(must=[], should=[], exclude=[], entities=[], topic_embedding=None)
    base.update(kw)
    return evaluate(story=story, **base)


# ------------------------------------------------------------- the gates


def test_exclude_gate_beats_a_perfect_score() -> None:
    """M3 exit criterion: no score overrides 'not gaming GPUs'."""
    story = _story("Nvidia GPU benchmark dominates gaming charts", [1.0, 0.0])
    score, matched = _eval(
        story,
        must=["nvidia", "gpu", "benchmark"],
        should=["charts"],
        exclude=["gaming"],
        topic_embedding=[1.0, 0.0],  # cosine 1.0 -- and it must not matter
    )
    assert score == 0.0
    assert matched == []


def test_no_must_hit_is_zero() -> None:
    score, _ = _eval(_story("Apple releases new iPad"), must=["nvidia"])
    assert score == 0.0


def test_entity_gate_requires_an_actor() -> None:
    story = _story("New chip factory announced in Arizona")
    score, _ = _eval(story, must=["chip"], entities=["TSMC"])
    assert score == 0.0
    score2, _ = _eval(_story("TSMC chip factory announced"), must=["chip"], entities=["TSMC"])
    assert score2 > 0.0


# ---------------------------------------------------- word-boundary matching


def test_terms_match_words_not_substrings() -> None:
    """'AI' must not match 'said'; 'EV' must not match 'ever'."""
    assert _eval(_story("The CEO said everything is fine"), must=["AI", "EV"])[0] == 0.0
    assert _eval(_story("New AI model raises the bar"), must=["AI"])[0] > 0.0


def test_multiword_and_hyphenated_terms_match() -> None:
    story = _story("A solid-state battery breakthrough for electric vehicles")
    score, matched = _eval(story, must=["solid state battery", "electric vehicle"])
    assert score > 0.0
    assert "solid state battery" in matched


# ------------------------------------------------------------------ scoring


def test_shoulds_raise_the_score() -> None:
    story = _story("Nvidia GPU export controls tighten for datacenter chips")
    bare, _ = _eval(story, must=["gpu"])
    boosted, _ = _eval(story, must=["gpu"], should=["export controls", "datacenter"])
    assert boosted > bare


def test_cosine_contributes_when_both_vectors_exist() -> None:
    story = _story("Nvidia GPU news", [1.0, 0.0])
    aligned, _ = _eval(story, must=["gpu"], topic_embedding=[1.0, 0.0])
    orthogonal, _ = _eval(story, must=["gpu"], topic_embedding=[0.0, 1.0])
    assert aligned > orthogonal


# -------------------------------------------------- the global block gate


def _blocked(title: str, description: str | None = None, entities: list[str] | None = None):
    st = searchable(title, description, entities or [])
    return blocked(StoryText(text=st.text, embedding=None), DEFAULT_BLOCK_TERMS)


def test_block_hits_the_title() -> None:
    assert _blocked("Israel unveils a new AI defence system") == "israel"


def test_block_hits_the_publisher_description() -> None:
    assert _blocked("A funding round", "The Tel Aviv startup raised $40m") == "tel aviv"


def test_block_hits_an_extracted_entity() -> None:
    assert _blocked("Spyware vendor sued again", None, ["NSO Group"]) == "nso group"


def test_block_matches_variants_not_stems() -> None:
    """'israel' must not be relied on to catch 'israeli' -- boundaries are hard."""
    assert _blocked("An Israeli chip designer ships silicon") == "israeli"
    assert _blocked("Israelis are adopting the tool fast") == "israelis"


def test_block_respects_word_boundaries() -> None:
    """The gate is containment on words, not on substrings.

    Each of these embeds a blocklist term inside a longer, innocent word. A
    naive `term in text` would drop all four.
    """
    assert _blocked("A gazebo maker goes digital") is None  # gaza
    assert _blocked("The hamster wheel of model releases") is None  # hamas
    assert _blocked("Midfield sensors for autonomous football") is None  # idf
    assert _blocked("Zionista is a fictional startup name") is None  # zionist


def test_block_is_case_and_punctuation_insensitive() -> None:
    assert _blocked("ISRAEL'S cyber sector booms") == "israels"
    assert _blocked("Tel-Aviv based lab open-sources a model") == "tel aviv"


def test_ordinary_ai_news_passes_the_gate() -> None:
    assert _blocked("OpenAI ships a new reasoning model") is None
    assert _blocked("Anthropic raises at a $60bn valuation") is None


def test_empty_blocklist_disables_the_gate() -> None:
    st = searchable("Israel unveils a new AI defence system", None, [])
    assert blocked(StoryText(text=st.text, embedding=None), []) is None


# ------------------------------------------------------ the publisher ban


def test_site_ban_matches_the_exact_domain() -> None:
    assert site_blocked("bbc.co.uk", DEFAULT_BLOCK_SITES) == "bbc.co.uk"


def test_site_ban_covers_subdomains() -> None:
    """A ban a subdomain walks around is not a ban."""
    assert site_blocked("news.bbc.co.uk", DEFAULT_BLOCK_SITES) == "bbc.co.uk"
    assert site_blocked("feeds.bbci.co.uk", DEFAULT_BLOCK_SITES) is None  # different domain


def test_site_ban_ignores_www_and_case() -> None:
    assert site_blocked("WWW.BBC.CO.UK", DEFAULT_BLOCK_SITES) == "bbc.co.uk"


def test_site_ban_does_not_match_on_suffix_alone() -> None:
    """'notbbc.co.uk' ends with the ban string but is a different publisher."""
    assert site_blocked("notbbc.co.uk", DEFAULT_BLOCK_SITES) is None


def test_site_ban_tolerates_missing_domain() -> None:
    assert site_blocked(None, DEFAULT_BLOCK_SITES) is None
    assert site_blocked("", DEFAULT_BLOCK_SITES) is None


def test_empty_site_ban_list_allows_everything() -> None:
    assert site_blocked("bbc.co.uk", []) is None


def test_banned_publisher_is_not_in_the_seed_list() -> None:
    """The gate stops serving; removing the seed stops it coming back."""
    from techtrend.shared.collect.seeds import TECH

    assert not [s for s in TECH if site_blocked(s["domain"], DEFAULT_BLOCK_SITES)]
