"""Collect stage units: canonicalisation, parsing, scheduling, fetcher politeness."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import httpx
import pytest
import respx

from techtrend.shared.collect import schedule
from techtrend.shared.collect.fetcher import PoliteFetcher, RobotsDisallowed
from techtrend.shared.collect.parse import parse_feed, parse_sitemap
from techtrend.shared.collect.urls import canonical, url_hash

# ------------------------------------------------------------- canonical URLs


def test_canonical_strips_tracking_params_and_fragment() -> None:
    url = "HTTPS://WWW.Example.com:443/a/b?utm_source=x&id=7&fbclid=abc#frag"
    assert canonical(url) == "https://www.example.com/a/b?id=7"


def test_canonical_keeps_meaningful_query() -> None:
    assert canonical("https://ex.com/story?p=2") == "https://ex.com/story?p=2"


def test_url_hash_is_stable_across_tracking_noise() -> None:
    a = url_hash("https://ex.com/x?utm_campaign=a")
    b = url_hash("https://ex.com/x")
    assert a == b


# ------------------------------------------------------------------- parsing

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>First</title><link>https://ex.com/1</link>
<pubDate>Thu, 07 Aug 2025 10:00:00 GMT</pubDate></item>
<item><title>No link skipped</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>T</title>
<entry><title>A1</title><link href="https://ex.com/a1"/>
<updated>2025-08-07T10:00:00Z</updated></entry>
</feed>"""

SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://ex.com/n1</loc>
  <news:news><news:title>N1</news:title>
  <news:publication_date>2025-08-07T09:30:00Z</news:publication_date></news:news>
</url>
<url><loc>ftp://bad</loc></url>
</urlset>"""


def test_parse_rss() -> None:
    links = parse_feed(RSS)
    assert len(links) == 1
    assert links[0].url == "https://ex.com/1"
    assert links[0].title == "First"
    assert links[0].published == datetime(2025, 8, 7, 10, 0, tzinfo=UTC)


def test_parse_atom() -> None:
    links = parse_feed(ATOM)
    assert [(li.url, li.title) for li in links] == [("https://ex.com/a1", "A1")]


def test_parse_sitemap_reads_news_metadata_and_skips_non_http() -> None:
    links = parse_sitemap(SITEMAP)
    assert len(links) == 1
    assert links[0].title == "N1"
    assert links[0].published == datetime(2025, 8, 7, 9, 30, tzinfo=UTC)


def test_parsers_survive_garbage() -> None:
    assert parse_feed(b"not xml at all") == []
    assert parse_sitemap(b"<<<>>>") == []


# ---------------------------------------------------------------- scheduling


def test_publishing_speeds_up_but_never_below_tier_base() -> None:
    nxt = schedule.after_check("A", 480, 2, published=True)
    assert nxt.interval_s == 240
    assert nxt.quiet_streak == 0
    assert schedule.after_check("A", 130, 0, published=True).interval_s == 120  # floor


def test_three_quiet_checks_back_off_with_a_cap() -> None:
    n1 = schedule.after_check("B", 600, 0, published=False)
    assert (n1.interval_s, n1.quiet_streak) == (600, 1)  # not yet
    n3 = schedule.after_check("B", 600, 2, published=False)
    assert n3.interval_s == 900
    capped = schedule.after_check("B", 600 * 8, 5, published=False)
    assert capped.interval_s == 600 * 8  # 8x base cap


def test_failures_back_off_exponentially_and_park_at_ten() -> None:
    nxt = schedule.after_failure("A", 120, 0)
    assert nxt.interval_s == 240
    assert nxt.failure_streak == 1
    assert schedule.after_failure("A", 6 * 3600, 8).interval_s == 6 * 3600  # cap
    assert schedule.after_failure("A", 120, 9).failure_streak == schedule.PARKED_FAILURE_STREAK


# -------------------------------------------------- fetcher politeness rules


def test_fetcher_has_no_auth_or_cookie_parameter() -> None:
    """Invariant #4 by absence: you cannot hand the fetcher credentials."""
    params = set(inspect.signature(PoliteFetcher.get).parameters)
    assert params == {"self", "url", "etag", "last_modified"}


@respx.mock
async def test_conditional_get_sends_validators_and_honest_ua() -> None:
    respx.get("https://ex.com/robots.txt").respond(404)
    route = respx.get("https://ex.com/feed").respond(304)
    f = PoliteFetcher()
    try:
        resp = await f.get("https://ex.com/feed", etag='W/"abc"', last_modified="yesterday")
    finally:
        await f.aclose()
    assert resp.not_modified
    sent = route.calls.last.request
    assert sent.headers["If-None-Match"] == 'W/"abc"'
    assert sent.headers["If-Modified-Since"] == "yesterday"
    assert "TechTrendBot" in sent.headers["User-Agent"]
    assert "@" in sent.headers["User-Agent"]  # contact address present


@respx.mock
async def test_cookies_do_not_persist_between_requests() -> None:
    """Paywalls meter by cookie; the fetcher must not behave like a browser."""
    respx.get("https://ex.com/robots.txt").respond(404)
    respx.get("https://ex.com/a").respond(200, headers={"Set-Cookie": "meter=1; Path=/"})
    route_b = respx.get("https://ex.com/b").respond(200)
    f = PoliteFetcher()
    try:
        await f.get("https://ex.com/a")
        await f.get("https://ex.com/b")
    finally:
        await f.aclose()
    assert "cookie" not in {k.lower() for k in route_b.calls.last.request.headers}


@respx.mock
async def test_robots_disallow_is_an_exception_not_a_result() -> None:
    respx.get("https://ex.com/robots.txt").respond(200, text="User-agent: *\nDisallow: /private/")
    f = PoliteFetcher()
    try:
        with pytest.raises(RobotsDisallowed):
            await f.get("https://ex.com/private/feed")
    finally:
        await f.aclose()


@respx.mock
async def test_unreachable_robots_does_not_stall_collection() -> None:
    respx.get("https://ex.com/robots.txt").mock(side_effect=httpx.ConnectError("down"))
    respx.get("https://ex.com/feed").respond(200, content=b"")
    f = PoliteFetcher()
    try:
        resp = await f.get("https://ex.com/feed")
    finally:
        await f.aclose()
    assert resp.status == 200
