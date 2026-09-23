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

import httpx

from techtrend.platform.config import settings
from techtrend.platform.telemetry import log

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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
    """One grounded question in, one answer plus its sources out."""
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
    url = _ENDPOINT.format(model=s.gemini_model)
    async with httpx.AsyncClient(timeout=s.gemini_timeout_s) as c:
        r = await c.post(
            url,
            headers={
                "x-goog-api-key": s.gemini_api_key.get_secret_value(),
                "Content-Type": "application/json",
            },
            content=json.dumps(body),
        )
    if r.status_code == 429:
        raise QuotaExceeded(r.text[:300])
    r.raise_for_status()
    return _parse(r.json())


def _parse(payload: dict) -> Brief:
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
