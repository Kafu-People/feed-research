"""Gemini with Google Search grounding -- the research half of the system.

This is the only place another provider is called, and it does ONE thing:
put a question to Google's index and return the answer with its sources.

Why a second provider at all. The crawler reports what publishers published;
it cannot report what people posted on Reddit or a forum, because Reddit's
robots.txt forbids crawling it and `PoliteFetcher` obeys that by invariant.
Google licenses that content and indexes it, so asking Google is legitimate
where crawling it is not. The line this module must never cross: it returns
an answer and a list of LINKS. Nothing downstream fetches those links -- doing
so would route around the robots.txt the crawler respects, using Google as the
laundry. Links stay links.

Deliberately NOT part of the Anthropic client protocol in `ai/client.py`.
That protocol is about judging and writing, all of it pinned to Haiku by
operator rule; this is retrieval from a different vendor with a different
failure model, and folding them together would make `ai_fake` mean two things.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from techtrend.platform.config import settings
from techtrend.platform.telemetry import log

_ENDPOINT = "{base}/v1beta/models/{model}:generateContent"


def _url(model: str) -> str:
    return _ENDPOINT.format(base=settings().gemini_base_url.rstrip("/"), model=model)

# The house style, same rule as the Anthropic prompts in ai/prompts/. Without
# it a brief is written in the register of the pages it read -- forum slang and
# press-release English -- which is the hardest possible mix for the reader
# this channel is for.
_STYLE = """Write for a smart adult who reads English as a SECOND language.
They understand technology. They do not know English idioms.

- No idioms and no phrasal verbs. Say "released", not "rolled out". Say
  "repeated", not "doubled down". Say "invented", not "came up with".
- Use the commoner of two words that mean the same thing: buy not acquire,
  try not attempt, use not utilise, about not approximately, later not
  subsequently.
- Say who did what. "Google raised the price", not "the price was raised".
- One fact per sentence. Short sentences.
- Explain any industry term the first time you use it, in a few plain words.
- No hype. Say what was claimed and who claimed it.

## Answer in TWO parts, separated by a line containing only ---TABLES---

The same findings, told twice, because they are read for different reasons.

PART ONE is the WRITTEN EXPLANATION. Flowing paragraphs, the way you would
explain the subject to someone who asked you about it. Cover everything you
found. Work through it in a sensible order, one subject per paragraph.

Part one has NO bullet points, NO numbered lists, NO headings and NO tables.
Those chop an explanation into fragments and leave the reader to reassemble
it. Write sentences that connect: this happened, which means this, which is
why this platform pays more than that one. If you are describing five
platforms, that is five paragraphs of prose, not a list of five bullets.

PART TWO is the SAME information as tables, and almost nothing else. This is
for the reader who wants to compare and decide rather than understand. One
table per thing being compared, with a short `##` heading above each. Four or
five columns at most so it stays readable on a phone. A one-line note under a
table is fine; paragraphs are not.

Never omit a part. If there is genuinely nothing to tabulate -- a quiet day
with two news items -- write the marker anyway and put one short table under
it.

Use **bold** on the fact that matters in a sentence -- the platform name, the
number, the verdict -- in both parts. That is the only markup part one uses.

Markdown is converted to Slack formatting before posting, so bold and the
part-two tables survive exactly as written."""


class NotConfigured(RuntimeError):
    """No API key. The brief stage is inert rather than broken."""


class Transient(RuntimeError):
    """A 5xx or a timeout -- Google is busy, not refusing.

    Distinct from QuotaExceeded on purpose. A quota error means billing is off
    and retrying changes nothing; this means try again shortly. Without the
    split, a 503 during one afternoon cost a topic its whole day, because the
    caller treated every failure as "skip until tomorrow".
    """


class Denied(RuntimeError):
    """HTTP 403 -- the project is blocked, not the request.

    Its own type because it needs a human, not a retry and not a fallback
    model. Seen 2026-09-26: `models.list` kept returning 200 while every
    `generateContent` answered "Your project has been denied access", so the
    key was valid and the project was not. Swallowed as a generic failure it
    looked like empty summaries: the hourly report posted headlines with
    nothing under them for hours, and the log said `gemini.summary_failed`
    without the reason.
    """


class Depleted(RuntimeError):
    """HTTP 402 -- the prepaid credits are gone.

    Its own type for the same reason `Denied` has one: retrying and falling
    back to another model both change nothing, because the project cannot bill
    at all. Seen 2026-10-01, and it cost a question to find out. A one-off
    `/techtrend question` raised a bare HTTPStatusError, `_one` logged it as a
    generic `brief.failed` with a traceback, the job was marked done, and the
    person who asked got silence. The reason was in Google's response body the
    whole time: "Your prepayment credits are depleted."
    """


class QuotaExceeded(RuntimeError):
    """HTTP 429.

    Grounding is billed per search, and a project without billing enabled has
    NO grounding quota at all -- plain generation on the same key and the same
    model succeeds, and the grounded call 429s. That is the shape of "billing
    is off", not "you are going too fast", so the caller must not treat it as
    a retryable rate limit and hammer it.
    """


@dataclass(frozen=True)
class Source:
    title: str
    uri: str


# The model is told to separate its two parts with this line and nothing else.
TABLES_MARKER = "---TABLES---"


@dataclass(frozen=True)
class Brief:
    text: str
    sources: list[Source] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    @property
    def parts(self) -> tuple[str, str]:
        """(analysis, tables). The tables half is empty when the model wrote
        no marker, which is the fallback the caller has to handle rather than
        a failure -- a brief with only prose is still worth posting."""
        if TABLES_MARKER not in self.text:
            return self.text.strip(), ""
        head, _, tail = self.text.partition(TABLES_MARKER)
        return head.strip(), tail.strip()

    @property
    def searches(self) -> int:
        """What this cost, in the only unit Google bills for."""
        return len(self.queries)


async def research(prompt: str) -> Brief:
    """One grounded question in, one answer plus its sources out.

    Falls back to a second model when the first is busy. Google's flash
    models go unavailable in spikes, and an answer from the smaller model
    beats no answer today.
    """
    s = settings()
    try:
        return await _ask(prompt, s.gemini_model)
    except Transient:
        if not s.gemini_fallback_model or s.gemini_fallback_model == s.gemini_model:
            raise
        log.warning("gemini.falling_back", frm=s.gemini_model, to=s.gemini_fallback_model)
        return await _ask(prompt, s.gemini_fallback_model)


async def write(system: str, user: str, *, model: str | None = None) -> tuple[str, int, int]:
    """Plain generation, NO search grounding. Returns (text, in_tokens, out).

    The other half of this module. `research` asks Google a question and is
    billed per search; this one just writes, and is billed per token -- which
    is the right shape for summarising an article the crawler already stored.
    Grounding there would be worse as well as dearer: the summary must
    describe THAT article, not the web's opinion of its subject.
    """
    s = settings()
    if s.gemini_api_key is None:
        raise NotConfigured("GEMINI_API_KEY is not set")
    body = {
        "contents": [{"parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
    }
    url = _url(model or s.gemini_model)
    async with httpx.AsyncClient(timeout=s.gemini_timeout_s) as c:
        try:
            r = await c.post(
                url,
                headers={
                    "x-goog-api-key": s.gemini_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                content=json.dumps(body),
            )
        except httpx.HTTPError as e:
            raise Transient(f"gemini unreachable: {e!r}") from e
    if r.status_code == 402:
        raise Depleted(r.text[:300])
    if r.status_code == 403:
        raise Denied(r.text[:300])
    if r.status_code == 429:
        raise QuotaExceeded(r.text[:300])
    if r.status_code >= 500:
        raise Transient(f"gemini {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    payload = r.json()
    cands = payload.get("candidates") or []
    if not cands:
        log.warning("gemini.no_candidate", feedback=payload.get("promptFeedback"))
        return "", 0, 0
    parts = (cands[0].get("content") or {}).get("parts") or []
    text_out = "".join(p.get("text", "") for p in parts).strip()
    usage = payload.get("usageMetadata") or {}
    return (
        text_out,
        int(usage.get("promptTokenCount", 0)),
        int(usage.get("candidatesTokenCount", 0)),
    )


async def _ask(prompt: str, model: str) -> Brief:
    s = settings()
    if s.gemini_api_key is None:
        raise NotConfigured("GEMINI_API_KEY is not set")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": _STYLE}]},
        # The tool the whole feature rests on. Without it the model answers
        # from training data, which for "what did people post this week" is
        # worse than no answer -- it is a confident one about last year.
        "tools": [{"google_search": {}}],
    }
    url = _url(model)
    async with httpx.AsyncClient(timeout=s.gemini_timeout_s) as c:
        try:
            r = await c.post(
                url,
                headers={
                    "x-goog-api-key": s.gemini_api_key.get_secret_value(),
                    "Content-Type": "application/json",
                },
                content=json.dumps(body),
            )
        except httpx.HTTPError as e:
            # A timeout on a two-minute grounded search is Google being slow,
            # not the request being wrong.
            raise Transient(f"gemini unreachable: {e!r}") from e
    if r.status_code == 402:
        # The same branch `_ask` grew, and for the sharper reason: an unnamed
        # 402 here is how the hourly report posts headlines with nothing under
        # them, which is the exact failure `Denied` was written about.
        raise Depleted(r.text[:300])
    if r.status_code == 403:
        raise Denied(r.text[:300])
    if r.status_code == 429:
        raise QuotaExceeded(r.text[:300])
    if r.status_code >= 500:
        raise Transient(f"gemini {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    return _parse(r.json())


def _parse(payload: dict[str, Any]) -> Brief:
    """Pull the answer and its grounding out of a response.

    Defensive about shape: a blocked or empty candidate is a Brief with no
    text rather than a KeyError, because the caller's job is to decide whether
    there is enough here to post, and it cannot decide that from a traceback.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        log.warning("gemini.no_candidate", feedback=payload.get("promptFeedback"))
        return Brief(text="")
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()

    meta = cand.get("groundingMetadata") or {}
    sources = []
    seen: set[str] = set()
    for chunk in meta.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        uri, title = web.get("uri"), web.get("title")
        # The same domain is cited many times in one answer; the reader wants
        # a source list, not a citation list.
        if uri and uri not in seen:
            seen.add(uri)
            sources.append(Source(title=str(title or uri), uri=str(uri)))
    return Brief(text=text, sources=sources, queries=list(meta.get("webSearchQueries") or []))
