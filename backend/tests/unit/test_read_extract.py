"""Read stage units: JSON-LD first, trafilatura fallback, dates, body floor."""

from __future__ import annotations

from datetime import UTC, datetime

from techtrend.shared.read.extract import extract_body, extract_jsonld, parse_date

PAGE = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle",
 "headline":"Chips are down",
 "datePublished":"2026-08-07T08:00:00Z",
 "author":{"@type":"Person","name":"A. Writer"},
 "image":["https://ex.com/i.jpg"],
 "inLanguage":"en-US"}
</script></head><body><p>hi</p></body></html>"""

GRAPH_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Organization","name":"Ex"},
  {"@type":["Article","TechArticle"],"headline":"Graphed","datePublished":"2026-08-07"}
]}</script></head><body></body></html>"""


def test_jsonld_newsarticle() -> None:
    m = extract_jsonld(PAGE)
    assert m.source == "jsonld"
    assert m.headline == "Chips are down"
    assert m.published_at == datetime(2026, 8, 7, 8, 0, tzinfo=UTC)
    assert m.author == "A. Writer"
    assert m.image == "https://ex.com/i.jpg"
    assert m.language == "en"


def test_jsonld_graph_and_type_list() -> None:
    m = extract_jsonld(GRAPH_PAGE)
    assert m.headline == "Graphed"
    assert m.published_at == datetime(2026, 8, 7, tzinfo=UTC)


def test_no_jsonld_is_not_an_error() -> None:
    assert extract_jsonld("<html><body>plain</body></html>").source == "none"


def test_broken_jsonld_is_skipped() -> None:
    html = '<script type="application/ld+json">{broken</script>'
    assert extract_jsonld(html).source == "none"


def test_parse_date_iso_rfc2822_and_garbage() -> None:
    assert parse_date("2026-08-07T10:00:00Z") == datetime(2026, 8, 7, 10, tzinfo=UTC)
    assert parse_date("Thu, 07 Aug 2026 10:00:00 GMT") == datetime(2026, 8, 7, 10, tzinfo=UTC)
    naive = parse_date("2026-08-07T10:00:00")
    assert naive is not None and naive.tzinfo is not None  # naive -> UTC
    assert parse_date("not a date") is None
    assert parse_date(None) is None


def test_tiny_body_is_dropped_not_stored() -> None:
    """Bad bodies poison embeddings -- a floor, not a warning."""
    assert extract_body("<html><body><p>too short</p></body></html>") is None


def test_real_body_is_extracted() -> None:
    words = " ".join(f"word{i} content sentence" for i in range(60))
    html = f"<html><body><article><h1>T</h1><p>{words}</p></article></body></html>"
    body = extract_body(html)
    assert body is not None
    assert "word3" in body.text
    assert 0 < body.confidence <= 1.0
