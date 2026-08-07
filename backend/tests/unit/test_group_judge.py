"""M2 units: entities, clustering gates, verification, hedge, importance."""

from __future__ import annotations

from techtrend.ai.schemas import JudgeResult
from techtrend.shared.group.cluster import Candidate, jaccard, pick_best, title_tokens
from techtrend.shared.judge.hedge import hedge_ratio
from techtrend.shared.judge.verify import normalize, verify_numbers, verify_rewritten
from techtrend.shared.judge.worker import _authority_guard, _importance
from techtrend.shared.read.entities import entity_tokens, extract_entities

# ------------------------------------------------------------------ entities

BODY = (
    "OpenAI said on Thursday it will remove the daily limit for free users. "
    "The new default model GPT-5.6 Luna will be available to all users now."
)


def test_titlecase_headline_does_not_produce_junk_spans() -> None:
    ents = extract_entities("Free ChatGPT Users Get Unlimited Text Chats", BODY)
    tokens = entity_tokens(ents)
    assert "chatgpt" in tokens
    assert "users" not in tokens  # seen lowercase in body -> not an entity
    assert "free" not in tokens  # stop-listed headline word
    assert "get" not in tokens


def test_internal_caps_and_digits_always_qualify() -> None:
    tokens = entity_tokens(extract_entities("iPhone 18 and H100 beat GPT-5.6", None))
    assert {"iphone", "h100", "gpt-5.6"} <= tokens


def test_spans_do_not_cross_sentence_boundaries() -> None:
    ents = extract_entities("Luna arrives. OpenAI ships it.", None)
    assert "luna" in ents and "openai" in ents
    assert not any("luna" in e and "openai" in e for e in ents)


# ------------------------------------------------------------------ clustering


def _cand(cosine: float, title: str, entities: list[str]) -> Candidate:
    return Candidate(article_id=1, story_id=10, cosine=cosine, title=title, entities=entities)


def test_all_three_gates_must_agree() -> None:
    title = "OpenAI removes daily limit on free ChatGPT chats"
    ents = ["openai", "chatgpt"]
    same = _cand(0.95, "ChatGPT free users get unlimited chats says OpenAI", ["chatgpt", "openai"])
    close_meaning_only = _cand(0.97, "Best travel gadgets for the summer", ["gadgetco"])
    assert pick_best([same, close_meaning_only], title, ents) is same
    assert pick_best([close_meaning_only], title, ents) is None


def test_low_cosine_never_merges_despite_identical_title() -> None:
    c = _cand(0.5, "OpenAI removes daily limit on free ChatGPT chats", ["openai", "chatgpt"])
    assert pick_best([c], "OpenAI removes daily limit on free ChatGPT chats", ["openai"]) is None


def test_jaccard_and_title_tokens() -> None:
    assert jaccard(set("ab"), set("ab")) == 1.0
    assert jaccard(set(), set("a")) == 0.0
    assert "the" not in title_tokens("The OpenAI Deal")


# ---------------------------------------------------------------- verification


def _result(summary: str) -> JudgeResult:
    return JudgeResult(summary=summary, story_type="original_reporting", novelty=0.5)


def test_hallucinated_number_drops_the_sentence() -> None:
    source = "The company raised $1.2bn in new funding this quarter."
    out = verify_numbers(_result("It raised $1.2bn. Revenue grew 45%."), source)
    assert out.summary == "It raised $1.2bn."


def test_equivalent_number_forms_match() -> None:
    assert normalize("1.2bn") == normalize("1,200,000,000")
    out = verify_numbers(_result("It raised 1,200,000,000 dollars."), "a $1.2bn raise")
    assert out.summary  # kept: same number, different surface form


def test_copied_lede_fails_rewrite_check() -> None:
    lede = "OpenAI said on Thursday it will remove the daily limit for free users of ChatGPT."
    assert verify_rewritten("Totally fresh words about the change here.", [lede])
    assert not verify_rewritten(lede, [lede])


# ------------------------------------------------------------ hedge/importance


def test_hedge_ratio_scores_speculation() -> None:
    solid = "The company announced results. Revenue was reported in the filing."
    spec = "Reportedly the device may launch, sources say, and could possibly ship."
    assert hedge_ratio(spec) > hedge_ratio(solid)


def test_authority_guard_lifts_confirmations() -> None:
    class P:
        max_authority = 0.3

    assert _authority_guard(0.2, 0.9, [P()]) > 0.2  # blog -> Reuters is news
    assert _authority_guard(0.2, 0.9, []) == 0.2  # no prior: nothing to confirm


def test_importance_prefers_novel_confirmed_multisource() -> None:
    good = _importance(0.9, 0.9, 10, 0.0, "original_reporting")
    spam = _importance(0.1, 0.3, 1, 0.8, "speculation")
    assert good > spam
