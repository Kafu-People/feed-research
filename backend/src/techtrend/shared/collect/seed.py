"""Upsert the curated source list into `sites` and `endpoints`.

Idempotent: re-running updates names/tiers/flags and adds new feeds, but
never resets an endpoint's adaptive schedule.
"""

from __future__ import annotations

from sqlalchemy import text

from techtrend.platform.db import session_scope
from techtrend.shared.collect.schedule import TIER_BASE_S
from techtrend.shared.collect.seeds import TECH

_UPSERT_SITE = text("""
    INSERT INTO sites (domain, name, tier, authority, paywall)
    VALUES (:domain, :name, :tier, :authority, :paywall)
    ON CONFLICT (domain) DO UPDATE
       SET name = EXCLUDED.name, tier = EXCLUDED.tier,
           authority = EXCLUDED.authority, paywall = EXCLUDED.paywall
    RETURNING id
""")

_UPSERT_ENDPOINT = text("""
    INSERT INTO endpoints (site_id, url, kind, interval_s)
    VALUES (:site_id, :url, :kind, :interval_s)
    ON CONFLICT (site_id, url) DO NOTHING
""")


async def seed_sites() -> dict[str, int]:
    sites = endpoints = 0
    async with session_scope() as s:
        for seed in TECH:
            site_id = (
                await s.execute(
                    _UPSERT_SITE,
                    {
                        "domain": seed["domain"],
                        "name": seed["name"],
                        "tier": seed["tier"],
                        "authority": seed["authority"],
                        "paywall": seed["paywall"],
                    },
                )
            ).scalar_one()
            sites += 1
            for url in seed["feeds"]:
                await s.execute(
                    _UPSERT_ENDPOINT,
                    {
                        "site_id": site_id,
                        "url": url,
                        "kind": "sitemap" if "sitemap" in url else "feed",
                        "interval_s": TIER_BASE_S[seed["tier"]],
                    },
                )
                endpoints += 1
    return {"sites": sites, "endpoints": endpoints}
