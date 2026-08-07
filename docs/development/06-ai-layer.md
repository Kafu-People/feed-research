# 6 — AI layer

← [Worker stages](05-worker-stages.md) · [Dev README](README.md) · next → [API surface](07-api.md)

**Every Claude call in the system lives in `techtrend/ai/`.** Two call sites exist:

| Call | Where | Volume | Latency | Cost profile |
| --- | --- | --- | --- | --- |
| **Judge** | `judge` worker | one per **story** | seconds–hours | **the dominant AI cost** |
| **Distill** | topic creation (API path) | one per topic created | **~2s, user is waiting** | negligible |

The `import-linter` contract in [repo layout](01-repo-layout.md) forbids `api/` and
`personal/` from importing `techtrend.ai` — so a request handler physically cannot make a
judging call. That is what keeps the cost model in [cost](../architecture/13-cost.md) true:
AI spend scales with stories/day, not with users.

---

## Model

**`claude-opus-5`** for both calls.

| Property | Value | Consequence for us |
| --- | --- | --- |
| Context | 1M tokens | Fifty articles about one event fit comfortably in one call |
| Max output | 128K | Never a constraint here |
| Thinking | **on by default** — omitting `thinking` runs adaptive | See the `max_tokens` warning below |
| Sampling params | `temperature` / `top_p` / `top_k` **return 400** | Steer with the prompt; there is no determinism knob |
| Prefill | **returns 400** | Structured outputs instead — which we want anyway |
| Prompt cache minimum | 512 tokens | Our system prompts clear it easily |
| Batch API | 50% cost | The main cost lever after one-call-per-story |

> ⚠️ **`max_tokens` caps thinking *plus* response text.** Thinking is on by default on
> `claude-opus-5`, so a `max_tokens` sized around the JSON output alone will truncate
> mid-answer. Every call below sets `max_tokens=16000` for a response that is typically
> well under 1K — the headroom is for thinking, not for output.

---

## Schemas — no free-text parsing anywhere

```python
# techtrend/ai/schemas.py
from typing import Literal
from pydantic import BaseModel, Field

StoryType = Literal[
    "original_reporting", "official_announcement", "analysis",
    "rewrite", "roundup", "routine_data", "speculation",
]

class Fact(BaseModel):
    kind: Literal["entity", "number", "date", "decision", "quote"]
    value: str
    normalized: str | None = Field(
        default=None, description="Canonical form: '1.2bn' -> '1200000000'"
    )

class JudgeResult(BaseModel):
    summary: str = Field(description="Exactly two sentences, in our own words.")
    story_type: StoryType
    facts: list[Fact] = Field(description="Entities, numbers, dates, decisions, quotes.")
    novelty: float = Field(ge=0.0, le=1.0,
                           description="Fraction of facts absent from the prior coverage.")
    novelty_rationale: str

class TopicDraft(BaseModel):
    title: str
    must: list[str]
    should: list[str]
    entities: list[str]
    exclude: list[str]
    ambiguity: str | None = Field(
        default=None, description="One clarifying question, if the sentence is ambiguous."
    )
    options: list[str] = Field(default_factory=list)
```

Downstream code never sees a string that needs parsing — it sees `JudgeResult`. That is the
whole contract of this module.

---

## Client

```python
# techtrend/ai/client.py
import anthropic
from techtrend.platform.config import settings
from techtrend.platform import telemetry

MODEL = "claude-opus-5"

class AIClient:
    def __init__(self) -> None:
        # Credentials resolve from the environment (ANTHROPIC_API_KEY, or an
        # `ant auth login` profile). Never hardcode a key.
        self._c = anthropic.AsyncAnthropic(max_retries=3, timeout=120.0)

    async def judge(self, story, articles, *, prior_facts, interactive: bool) -> JudgeResult:
        if interactive:
            return await self._judge_now(story, articles, prior_facts)
        return await self._judge_batched(story, articles, prior_facts)
```

The SDK retries 429 and 5xx with exponential backoff by default; `max_retries=3` widens
that slightly. Do not hand-roll a retry loop on top of it.

---

## The interactive path (Tier A / breaking)

```python
# techtrend/ai/judge.py
from techtrend.ai.prompts import JUDGE_SYSTEM        # loaded from prompts/judge.md at import

async def _judge_now(self, story, articles, prior_facts) -> JudgeResult:
    resp = await self._c.messages.parse(
        model=MODEL,
        max_tokens=16000,                 # headroom for thinking, not for output
        system=[{
            "type": "text",
            "text": JUDGE_SYSTEM,          # frozen; no interpolation → stays cacheable
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": render_judge_input(story, articles, prior_facts)}],
        output_format=JudgeResult,
    )
    if resp.stop_reason == "refusal":      # ← check BEFORE reading content
        raise Refused(resp.stop_details.category if resp.stop_details else None)

    telemetry.observe_usage("judge.interactive", resp.usage)
    return resp.parsed_output
```

### Handle refusals — this is not hypothetical for a news app

`claude-opus-5` ships with elevated cybersecurity safeguards, and a declined request
returns **HTTP 200** with `stop_reason: "refusal"` and an empty or partial `content` array.
A news corpus contains security stories; benign coverage of a breach or a CVE can trip a
classifier. Code that reads `resp.content[0]` unconditionally will break on exactly the
stories we most want judged.

Two responses, in order:

```python
# 1. Server-side fallback — one round trip, no client-side logic.
resp = await self._c.beta.messages.create(
    model=MODEL,
    max_tokens=16000,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",                   # routes by refusal category
    system=[...], messages=[...],
    output_config={"format": {"type": "json_schema", "schema": JudgeResult.model_json_schema()}},
)

# 2. If the whole chain still refuses, degrade — don't drop the story.
if resp.stop_reason == "refusal":
    await mark_unjudged(story, reason="refusal")
```

**An unjudged story is not a dropped story.** `mark_unjudged` leaves `summary` and
`novelty_score` null; [ranking](05-worker-stages.md) treats a null novelty as neutral and
the card shows the headline and source without our summary. The user sees the event,
attributed to the publisher, which is the honest outcome — and it keeps
[invariant #6](../architecture/14-invariants.md) intact.

`fallbacks` is **rejected on the Batches API**, so the batch path relies on the degrade
branch alone.

---

## The batch path (the tail — and the cost lever)

Most stories are not breaking. The Batch API runs them at **50% of standard price**, and
most complete well inside an hour.

```python
# techtrend/ai/batch.py
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

JUDGE_SCHEMA = {"type": "json_schema", "schema": JudgeResult.model_json_schema()}

async def submit(self, items: list[JudgeItem]) -> str:
    batch = await self._c.messages.batches.create(requests=[
        Request(
            custom_id=f"story-{it.story_id}",
            params=MessageCreateParamsNonStreaming(
                model=MODEL,
                max_tokens=16000,
                system=[{"type": "text", "text": JUDGE_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": render_judge_input(*it)}],
                # .parse() is not available on batches — declare the schema
                # explicitly and validate client-side on collection.
                output_config={"format": JUDGE_SCHEMA},
            ),
        )
        for it in items
    ])
    return batch.id

async def collect(self, batch_id: str) -> dict[int, JudgeResult | None]:
    batch = await self._c.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        raise NotReady(batch_id)

    out: dict[int, JudgeResult | None] = {}
    async for r in await self._c.messages.batches.results(batch_id):
        sid = int(r.custom_id.removeprefix("story-"))     # ← key by custom_id, NEVER position
        if r.result.type != "succeeded":
            out[sid] = None
            continue
        msg = r.result.message
        if msg.stop_reason == "refusal":
            out[sid] = None
            continue
        text = next(b.text for b in msg.content if b.type == "text")
        out[sid] = JudgeResult.model_validate_json(text)
    return out
```

**Results arrive in any order.** Keying by `custom_id` is not stylistic — positional
assumptions silently attach one story's summary to another, which is the single worst bug
this system could ship.

Batch lifecycle runs as an ordinary queue stage: `judge_batch_submit` collects pending
stories every ~5 minutes and enqueues `judge_batch_poll` with `run_after = now() + 5min`,
which re-enqueues itself until `processing_status == "ended"`. No new machinery
([job queue](04-job-queue.md)).

---

## Prompt caching

The judge system prompt is large (story-type definitions, novelty rubric, summary rules)
and identical on every call — an ideal cached prefix.

**Caching is a prefix match.** Any byte change anywhere in the prefix invalidates
everything after it. Render order is `tools` → `system` → `messages`, so the rules are:

```python
# ai/prompts/__init__.py
JUDGE_SYSTEM = (Path(__file__).parent / "judge.md").read_text()   # module-level, frozen
```

- Prompts are **files loaded once at import**, never f-strings. Interpolating a date,
  a story id, or a build hash into the system prompt silently kills the cache.
- Everything per-story goes in the **user** message, after the breakpoint.
- The prompt file is version-controlled; changing it is a deploy, and the first request
  after deploy pays a cache write.

Verify it in CI and in production:

```python
def observe_usage(stage: str, usage) -> None:
    telemetry.counter(f"ai.{stage}.input", usage.input_tokens)
    telemetry.counter(f"ai.{stage}.cache_read", usage.cache_read_input_tokens)
    telemetry.counter(f"ai.{stage}.cache_write", usage.cache_creation_input_tokens)
    telemetry.counter(f"ai.{stage}.output", usage.output_tokens)
```

**If `ai.judge.cache_read` is flat at zero across repeated calls, a silent invalidator has
been introduced.** That alert is cheap and catches an entire class of cost regression.

---

## Effort

`output_config: {"effort": ...}` controls thinking depth and total token spend. Accepted:
`low`, `medium`, `high` (default), `xhigh`, `max`.

| Call | Start at | Why |
| --- | --- | --- |
| **Judge** | `medium`, sweep down to `low` | Fact extraction and classification against provided source text. `low` and `medium` are unusually strong on this model; the novelty harness ([testing](12-testing.md)) is the arbiter, not intuition |
| **Distill** | `low` | The 2-second onboarding budget is a product requirement ([journey](../architecture/10-user-journey.md)) |

Do not disable thinking to save latency. On `claude-opus-5`, `thinking: {"type": "disabled"}`
has two documented failure modes (internal tags leaking into output; and with tools, calls
emitted as plain text that silently never run) and is rejected outright at `xhigh`/`max`
effort. Lowering `effort` is the cheaper, safer lever and gets most of the saving.

---

## The verification check — five lines, not optional

[Invariant #7](../architecture/14-invariants.md). Runs on **every** result, both paths,
before anything is persisted.

```python
# techtrend/shared/judge/verify.py
NUM = re.compile(r"[-+]?\d[\d,.]*\s*(?:%|bn|billion|m|million|k|thousand)?", re.I)

def normalize(tok: str) -> Decimal:
    """1.2bn == 1,200,000,000 == 1200000000"""
    ...

def verify_numbers(result: JudgeResult, articles: list[Article]) -> JudgeResult:
    source = {normalize(t) for a in articles for t in NUM.findall(searchable(a))}
    kept = [
        s for s in split_sentences(result.summary)
        if all(normalize(t) in source for t in NUM.findall(s))
    ]
    dropped = len(split_sentences(result.summary)) - len(kept)
    if dropped:
        telemetry.counter("judge.sentences_dropped", dropped)
    return result.model_copy(update={"summary": " ".join(kept)})
```

> **A confidently wrong summary is worse than no summary.** A hallucinated percentage in a
> financial story is the kind of mistake that ends the product's credibility in one
> screenshot. `judge.sentences_dropped` is a monitored metric, not a debug counter — a
> sustained rise means the prompt or the model changed underneath us.

### And the rewriting check

[Invariant #2](../architecture/14-invariants.md) — summaries must be genuinely rewritten,
not lightly edited ledes. This is a legal requirement, so it gets a check too:

```python
def verify_rewritten(summary: str, articles: list[Article], *, max_ngram_overlap=0.25) -> bool:
    """Reject a summary that reuses long verbatim runs from any source."""
    src = {shingles(searchable(a), n=8) for a in articles}
    return max((jaccard(shingles(summary, n=8), s) for s in src), default=0.0) <= max_ngram_overlap
```

A failing summary is discarded and the story is marked unjudged — same degrade path as a
refusal. We would rather ship no summary than an infringing one.

---

## The distiller

The one interactive call. It is on the onboarding critical path, so latency is a feature.

```python
# techtrend/ai/distill.py
async def distill(self, sentence: str, *, language: str = "en") -> TopicDraft:
    resp = await self._c.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": DISTILL_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": sentence}],
        output_format=TopicDraft,
    )
    if resp.stop_reason == "refusal":
        raise Refused(None)
    return resp.parsed_output
```

Two things the prompt must produce, both from [match](../architecture/07-match.md):

**Expansion is where the value is.** The user types "AI chips"; the draft must contain
H100, Blackwell, TSMC, ASML, entity list, BIS, and non-English spellings. It is the
difference between four results a week and fifteen a day, and it is what the distiller
eval measures ([testing](12-testing.md)).

**Ambiguity gets one question with buttons.** `TopicDraft.ambiguity` + `options` are how
*"Apple — the company or the fruit?"* reaches the UI. Unresolved ambiguity becomes a bad
feed the user cannot diagnose, so the schema makes asking cheap.

---

## Errors

Catch a chain, most specific first — never string-match a message:

```python
try:
    result = await self._c.messages.parse(...)
except anthropic.RateLimitError:
    raise RetryableError("rate limited")        # queue backs off ([job queue](04-job-queue.md))
except anthropic.APIStatusError as e:
    raise (RetryableError if e.status_code >= 500 else FatalError)(e.message)
except anthropic.APIConnectionError:
    raise RetryableError("connection")
```

`RetryableError` returns the job to `pending` with exponential backoff; `FatalError`
dead-letters it with the error text on the row.

---

## Cost control

| Lever | Effect | Where |
| --- | --- | --- |
| **One call per story** | 50 articles → 1 call | [Group](../architecture/05-group.md) must be right |
| **Batch API** | −50% on the non-urgent tail | This document |
| **Prompt caching** | Cache reads ≈ 0.1× input | Frozen system prompt |
| **Effort sweep** | Meaningful, quality-gated | Validated by the novelty harness |
| **Hedge score without a model** | One fewer call | Lexicon in `shared/judge/hedge.py` |

Estimate before shipping a prompt change:

```python
n = await client.messages.count_tokens(model=MODEL, system=[...], messages=[...])
```

Use `count_tokens`, never `tiktoken` — it is OpenAI's tokenizer and undercounts Claude
badly, worse still on code and non-English text.

**Watch `stories/day`, not `articles/day`.** If the AI bill rises without a traffic
increase, the cause is almost always clustering under-merging
([group](../architecture/05-group.md)) — the same root cause that degrades novelty and
puts duplicates on the dashboard. One bill, three symptoms, one fix.

---

## Changing the prompt

1. Edit `ai/prompts/judge.md`. Bump `JUDGE_PROMPT_VERSION`.
2. Run the **novelty harness** and the **verification suite** on the frozen fixture set
   ([testing](12-testing.md)).
3. Compare `judge.sentences_dropped` and the effort/cost delta against the previous
   version.
4. Ship. The first request after deploy pays a cache write; expect a one-off blip in
   `ai.judge.cache_write`.

Stories judged under an older prompt version keep their result — `stories.judged_at` plus
the version tag make a targeted re-judge a queue backfill, not a migration.
