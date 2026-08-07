"""Feed and news-sitemap parsing.

Both formats reduce to the same thing: a list of (url, title, published).
feedparser handles the decades of malformed RSS/Atom in the wild; sitemaps
are strict enough for a small XML walk (via defusedxml -- feeds are
attacker-controlled input).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
from defusedxml import ElementTree

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_NEWS_NS = "{http://www.google.com/schemas/sitemap-news/0.9}"


@dataclass(frozen=True)
class Link:
    url: str
    title: str | None = None
    published: datetime | None = None


def _from_struct(t: time.struct_time | None) -> datetime | None:
    if t is None:
        return None
    return datetime.fromtimestamp(time.mktime(t) - time.timezone, tz=UTC)


def parse_feed(body: bytes) -> list[Link]:
    """RSS or Atom -- feedparser sniffs which. Entries without a link are skipped."""
    parsed = feedparser.parse(body)
    links: list[Link] = []
    for e in parsed.entries:
        url = e.get("link")
        if not url or not url.startswith(("http://", "https://")):
            continue
        links.append(
            Link(
                url=url,
                title=e.get("title") or None,
                published=_from_struct(e.get("published_parsed") or e.get("updated_parsed")),
            )
        )
    return links


def _iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_sitemap(body: bytes) -> list[Link]:
    """Google news-sitemap: <url><loc> plus optional <news:news> metadata."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []
    links: list[Link] = []
    for url_el in root.iter(f"{_SITEMAP_NS}url"):
        loc = url_el.findtext(f"{_SITEMAP_NS}loc")
        if not loc or not loc.strip().startswith(("http://", "https://")):
            continue
        news = url_el.find(f"{_NEWS_NS}news")
        title = pub = None
        if news is not None:
            title = news.findtext(f"{_NEWS_NS}title")
            pub = news.findtext(f"{_NEWS_NS}publication_date")
        links.append(Link(url=loc.strip(), title=title, published=_iso(pub)))
    return links
