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


@dataclass(frozen=True)
class Brief:
    text: str
    sources: list[Source] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

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
