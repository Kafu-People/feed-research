"""Demo seed: a user, a topic, sites, judged stories, matches.

Makes the dashboard non-empty in seconds so ranking and client work can proceed
without waiting for a crawl. Real corpus seeding lands with M1.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from techtrend.platform.db import session_scope

DEMO = [
    ("Nvidia cleared to resume H20 sales to China", "Reuters", 0.92, 14, 2),
    ("ASML says licence rules cut Q3 China revenue", "Bloomberg", 0.81, 9, 6),
    ("Commerce adds four Chinese fabs to entity list", "AP", 0.88, 21, 26),
    ("TSMC lifts capex on advanced packaging demand", "FT", 0.64, 6, 30),
    ("Analysts raise Nvidia price targets after results", "CNBC", 0.31, 33, 8),
]


async def seed_demo(email: str, password_hash: str) -> dict[str, int]:
    """Idempotent enough to re-run during development."""
    async with session_scope() as s:
        user_id = await s.scalar(
            text(
                "INSERT INTO users (email, password_hash) VALUES (:e, :p)"
                " ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash"
                " RETURNING id"
            ),
            {"e": email, "p": password_hash},
        )

        topic_id = await s.scalar(
            text(
                "INSERT INTO topics (fingerprint, title, must, should, entities, exclude)"
                " VALUES (:fp, 'AI chip export controls',"
                "         ARRAY['ai chip','gpu','semiconductor','h100'],"
                "         ARRAY['tariff','sanctions','entity list','fab'],"
                "         ARRAY['nvidia','tsmc','china'],"
                "         ARRAY['gaming gpu review'])"
                " ON CONFLICT (fingerprint) DO UPDATE SET title = EXCLUDED.title"
                " RETURNING id"
            ),
            {"fp": hashlib.sha256(b"demo-topic").digest()},
        )

        await s.execute(
            text(
                "INSERT INTO subscriptions (user_id, topic_id, label)"
                " VALUES (:u, :t, 'AI chip export controls')"
                " ON CONFLICT DO NOTHING"
            ),
            {"u": user_id, "t": topic_id},
        )

        n = 0
        for title, source, importance, sources, hours in DEMO:
            site_id = await s.scalar(
                text(
                    "INSERT INTO sites (domain, name, tier, authority)"
                    " VALUES (:d, :n, 'A', :a)"
                    " ON CONFLICT (domain) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                ),
                {"d": f"{source.lower()}.com", "n": source, "a": min(0.95, importance + 0.1)},
            )
            url = f"https://{source.lower()}.com/{hashlib.md5(title.encode()).hexdigest()[:8]}"  # noqa: S324
            existing = await s.scalar(
                text("SELECT id FROM articles WHERE url_hash = :h"),
                {"h": hashlib.sha256(url.encode()).digest()},
            )
            if existing:
                continue

            story_id = await s.scalar(
                text(
                    "INSERT INTO stories (source_count, summary, story_type, novelty_score,"
                    " hedge_score, importance, judged_at)"
                    " VALUES (:sc, :sm, :st, :nov, 0.15, :imp, now()) RETURNING id"
                ),
                {
                    "sc": sources,
                    "sm": f"{title.rstrip('.')}. Reported across {sources} outlets.",
                    "st": "analysis" if importance < 0.4 else "original_reporting",
                    "nov": importance,
                    "imp": importance,
                },
            )
            article_id = await s.scalar(
                text(
                    "INSERT INTO articles (url, url_hash, site_id, title, published_at, story_id)"
                    " VALUES (:u, :h, :s, :t, :p, :st) RETURNING id"
                ),
                {
                    "u": url,
                    "h": hashlib.sha256(url.encode()).digest(),
                    "s": site_id,
                    "t": title,
                    "p": datetime.now(UTC) - timedelta(hours=hours),
                    "st": story_id,
                },
            )
            await s.execute(
                text("UPDATE stories SET display_article_id = :a WHERE id = :s"),
                {"a": article_id, "s": story_id},
            )
            await s.execute(
                text(
                    "INSERT INTO matches (topic_id, story_id, match_score, matched_by)"
                    " VALUES (:t, :s, 0.9, ARRAY['ai chip','nvidia'])"
                    " ON CONFLICT DO NOTHING"
                ),
                {"t": topic_id, "s": story_id},
            )
            n += 1

    return {"user_id": int(user_id or 0), "topic_id": int(topic_id or 0), "stories": n}
