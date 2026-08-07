"""PoliteFetcher -- every outbound HTTP request the pipeline makes goes through here.

The politeness rules are properties of this class, not policies in callers:

- robots.txt honoured (cached per host, refreshed every 12h)
- per-host concurrency <= 2, enforced by a semaphore per host -- and the limit
  itself is validated at startup (`per_host_concurrency: Field(ge=1, le=2)`)
- honest User-Agent with a contact address
- conditional GETs (ETag / Last-Modified) so "nothing new" costs ~nothing
- there is NO cookie jar and NO auth-header parameter: the class physically
  cannot bypass a paywall (invariant #4)
"""

from __future__ import annotations

import asyncio
import urllib.robotparser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from techtrend.platform.config import settings

_ROBOTS_TTL = timedelta(hours=12)


@dataclass(frozen=True)
class FetchResult:
    status: int
    body: bytes
    final_url: str
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class RobotsDisallowed(Exception):
    """robots.txt forbids this URL. Not retryable; not an error to log loudly."""


class PoliteFetcher:
    def __init__(self) -> None:
        s = settings()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": s.user_agent},
            timeout=s.fetch_timeout_s,
            follow_redirects=True,
            # No ambient credentials: proxies/netrc from the environment are
            # exactly the kind of side door invariant #4 rules out.
            trust_env=False,
        )
        self._per_host: dict[str, asyncio.Semaphore] = {}
        self._robots: dict[str, tuple[datetime, urllib.robotparser.RobotFileParser | None]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def _sem(self, host: str) -> asyncio.Semaphore:
        if host not in self._per_host:
            self._per_host[host] = asyncio.Semaphore(settings().per_host_concurrency)
        return self._per_host[host]

    async def _allowed(self, url: str) -> bool:
        if not settings().respect_robots:
            return True
        host = urlsplit(url).netloc
        now = datetime.now(UTC)
        cached = self._robots.get(host)
        if cached is None or now - cached[0] > _ROBOTS_TTL:
            rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                resp = await self._client.get(f"{urlsplit(url).scheme}://{host}/robots.txt")
                if resp.status_code == 200:
                    assert rp is not None
                    rp.parse(resp.text.splitlines())
                else:
                    rp = None  # no robots.txt -> everything allowed
            except httpx.HTTPError:
                rp = None  # unreachable robots.txt must not stall collection
            self._robots[host] = (now, rp)
            cached = self._robots[host]
        rp = cached[1]
        return rp is None or rp.can_fetch(settings().user_agent, url)

    async def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """One GET, conditionally if validators are given.

        Raises RobotsDisallowed rather than returning a result -- callers must
        not be able to ignore it by accident.
        """
        if not await self._allowed(url):
            raise RobotsDisallowed(url)

        headers = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        async with self._sem(urlsplit(url).netloc):
            resp = await self._client.get(url, headers=headers)
        # A cookie a response set must not shape the next request: paywalls and
        # metering work by cookie, and we are not a browser (invariant #4).
        self._client.cookies.clear()

        return FetchResult(
            status=resp.status_code,
            body=resp.content,
            final_url=str(resp.url),
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
