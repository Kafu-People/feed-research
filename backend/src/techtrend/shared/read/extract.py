"""Take the structured data first.

Publishers embed JSON-LD NewsArticle because Google requires it -- headline,
date, author, image. It is more accurate than any heuristic and does not
break on redesigns. Only the article BODY falls back to trafilatura, and a
low-confidence body is dropped rather than stored: bad text poisons
embeddings and summaries downstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import trafilatura

_LDJSON = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_ARTICLE_TYPES = {
    "NewsArticle",
    "Article",
    "BlogPosting",
    "ReportageNewsArticle",
    "TechArticle",
    "AnalysisNewsArticle",
}
_MIN_BODY_CHARS = 250  # shorter than this is boilerplate, not an article


@dataclass(frozen=True)
class Meta:
    headline: str | None = None
    published_at: datetime | None = None
    author: str | None = None
    image: str | None = None
    language: str | None = None
    source: str = "none"  # jsonld | none


@dataclass(frozen=True)
class Body:
    text: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Extraction:
    meta: Meta
    body: Body | None = None
    problems: list[str] = field(default_factory=list)


def parse_date(value: object) -> datetime | None:
    """ISO-8601 first (what JSON-LD should carry), RFC-2822 as a courtesy."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(v)
        except (ValueError, TypeError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _first(value: object) -> object:
    return value[0] if isinstance(value, list) and value else value


def _name(value: object) -> str | None:
    value = _first(value)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        n = value.get("name")
        return n.strip() if isinstance(n, str) and n.strip() else None
    return None


def _image(value: object) -> str | None:
    value = _first(value)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        u = value.get("url")
        return u.strip() if isinstance(u, str) and u.strip() else None
    return None


def _candidates(doc: object) -> list[dict[str, object]]:
    """JSON-LD comes as an object, a list, or an @graph -- flatten all three."""
    if isinstance(doc, list):
        return [c for d in doc for c in _candidates(d)]
    if not isinstance(doc, dict):
        return []
    graph = doc.get("@graph")
    if isinstance(graph, list):
        return _candidates(graph)
    types = doc.get("@type")
    names = {types} if isinstance(types, str) else set(types) if isinstance(types, list) else set()
    return [doc] if names & _ARTICLE_TYPES else []


def extract_jsonld(html: str) -> Meta:
    for m in _LDJSON.finditer(html):
        try:
            doc = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        for art in _candidates(doc):
            lang = art.get("inLanguage")
            lang_s = _first(lang)
            return Meta(
                headline=_name(art.get("headline")),
                published_at=parse_date(art.get("datePublished")),
                author=_name(art.get("author")),
                image=_image(art.get("image")),
                language=lang_s[:2].lower() if isinstance(lang_s, str) and lang_s else None,
                source="jsonld",
            )
    return Meta()


def extract_body(html: str, url: str | None = None) -> Body | None:
    """Trafilatura, then a floor: a tiny 'body' means extraction failed."""
    text = trafilatura.extract(html, url=url, include_comments=False)
    if not text or len(text) < _MIN_BODY_CHARS:
        return None
    # Crude but honest: confidence scales with how much real text came out.
    return Body(text=text, confidence=min(1.0, len(text) / 2000))


def extract(html: str, url: str | None = None) -> Extraction:
    meta = extract_jsonld(html)
    body = extract_body(html, url)
    problems = []
    if meta.source == "none":
        problems.append("no_jsonld")
    if body is None:
        problems.append("no_body")
    return Extraction(meta=meta, body=body, problems=problems)
