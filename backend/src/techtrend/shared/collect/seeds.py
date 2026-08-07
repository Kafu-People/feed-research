"""The launch source list -- tech domain.

Curated, not crawled: quality matters more than count, because every M1 exit
measurement (articles/day, JSON-LD rate, duplication) is taken against this
list. Feed URLs are best-effort -- a moved feed shows up as a failure streak
and in the nightly coverage diff, which is the designed detection path.

tier A = major outlets (2 min checks), B = specialist (10 min), C = tail/blogs (45 min).
"""

from __future__ import annotations

from typing import TypedDict


class Seed(TypedDict):
    domain: str
    name: str
    tier: str
    paywall: bool
    authority: float
    feeds: list[str]


def _s(
    domain: str,
    name: str,
    tier: str,
    feeds: list[str],
    *,
    paywall: bool = False,
    authority: float = 0.5,
) -> Seed:
    return Seed(
        domain=domain, name=name, tier=tier, paywall=paywall, authority=authority, feeds=feeds
    )


TECH: list[Seed] = [
    # ---- Tier A: major tech outlets --------------------------------------
    _s("theverge.com", "The Verge", "A", ["https://www.theverge.com/rss/index.xml"], authority=0.8),
    _s("arstechnica.com", "Ars Technica", "A", ["https://arstechnica.com/feed/"], authority=0.85),
    _s("techcrunch.com", "TechCrunch", "A", ["https://techcrunch.com/feed/"], authority=0.8),
    _s("wired.com", "Wired", "A", ["https://www.wired.com/feed/rss"], paywall=True, authority=0.8),
    _s("engadget.com", "Engadget", "A", ["https://www.engadget.com/rss.xml"], authority=0.7),
    _s("zdnet.com", "ZDNET", "A", ["https://www.zdnet.com/news/rss.xml"], authority=0.65),
    _s("cnet.com", "CNET", "A", ["https://www.cnet.com/rss/news/"], authority=0.65),
    _s(
        "theregister.com",
        "The Register",
        "A",
        ["https://www.theregister.com/headlines.atom"],
        authority=0.7,
    ),
    _s("venturebeat.com", "VentureBeat", "A", ["https://venturebeat.com/feed/"], authority=0.65),
    _s("gizmodo.com", "Gizmodo", "A", ["https://gizmodo.com/feed"], authority=0.6),
    _s(
        "macrumors.com",
        "MacRumors",
        "A",
        ["https://feeds.macrumors.com/MacRumors-All"],
        authority=0.65,
    ),
    _s("9to5mac.com", "9to5Mac", "A", ["https://9to5mac.com/feed/"], authority=0.65),
    _s(
        "tomshardware.com",
        "Tom's Hardware",
        "A",
        ["https://www.tomshardware.com/feeds/all"],
        authority=0.7,
    ),
    _s(
        "bleepingcomputer.com",
        "BleepingComputer",
        "A",
        ["https://www.bleepingcomputer.com/feed/"],
        authority=0.75,
    ),
    _s(
        "theinformation.com",
        "The Information",
        "A",
        ["https://www.theinformation.com/feed"],
        paywall=True,
        authority=0.85,
    ),
    # Mainstream outlets' tech desks -- high authority, often paywalled.
    _s(
        "nytimes.com",
        "NYT Technology",
        "A",
        ["https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"],
        paywall=True,
        authority=0.9,
    ),
    _s(
        "bbc.co.uk",
        "BBC Technology",
        "A",
        ["https://feeds.bbci.co.uk/news/technology/rss.xml"],
        authority=0.9,
    ),
    _s(
        "theguardian.com",
        "Guardian Technology",
        "A",
        ["https://www.theguardian.com/uk/technology/rss"],
        authority=0.85,
    ),
    _s(
        "cnbc.com",
        "CNBC Technology",
        "A",
        ["https://www.cnbc.com/id/19854910/device/rss/rss.html"],
        authority=0.8,
    ),
    _s(
        "wsj.com",
        "WSJ Tech",
        "A",
        ["https://feeds.a.dj.com/rss/RSSWSJD.xml"],
        paywall=True,
        authority=0.9,
    ),
    # ---- Tier B: specialist ----------------------------------------------
    _s("thenextweb.com", "The Next Web", "B", ["https://thenextweb.com/feed"]),
    _s("mashable.com", "Mashable", "B", ["https://mashable.com/feeds/rss/all"]),
    _s("digitaltrends.com", "Digital Trends", "B", ["https://www.digitaltrends.com/feed/"]),
    _s("techradar.com", "TechRadar", "B", ["https://www.techradar.com/rss"]),
    _s("9to5google.com", "9to5Google", "B", ["https://9to5google.com/feed/"]),
    _s(
        "androidauthority.com", "Android Authority", "B", ["https://www.androidauthority.com/feed/"]
    ),
    _s("androidpolice.com", "Android Police", "B", ["https://www.androidpolice.com/feed/"]),
    _s("xda-developers.com", "XDA Developers", "B", ["https://www.xda-developers.com/feed/"]),
    _s("appleinsider.com", "AppleInsider", "B", ["https://appleinsider.com/rss/news/"]),
    _s("siliconangle.com", "SiliconANGLE", "B", ["https://siliconangle.com/feed/"]),
    _s("hackaday.com", "Hackaday", "B", ["https://hackaday.com/feed/"]),
    _s("404media.co", "404 Media", "B", ["https://www.404media.co/rss/"], authority=0.7),
    _s(
        "restofworld.org",
        "Rest of World",
        "B",
        ["https://restofworld.org/feed/latest/"],
        authority=0.7,
    ),
    _s("techdirt.com", "Techdirt", "B", ["https://www.techdirt.com/feed/"]),
    _s("torrentfreak.com", "TorrentFreak", "B", ["https://torrentfreak.com/feed/"]),
    _s(
        "spectrum.ieee.org",
        "IEEE Spectrum",
        "B",
        ["https://spectrum.ieee.org/feeds/feed.rss"],
        authority=0.8,
    ),
    _s(
        "technologyreview.com",
        "MIT Technology Review",
        "B",
        ["https://www.technologyreview.com/feed/"],
        paywall=True,
        authority=0.8,
    ),
    # Security press
    _s(
        "thehackernews.com", "The Hacker News", "B", ["https://feeds.feedburner.com/TheHackersNews"]
    ),
    _s(
        "krebsonsecurity.com",
        "Krebs on Security",
        "B",
        ["https://krebsonsecurity.com/feed/"],
        authority=0.8,
    ),
    _s("darkreading.com", "Dark Reading", "B", ["https://www.darkreading.com/rss.xml"]),
    _s("securityweek.com", "SecurityWeek", "B", ["https://www.securityweek.com/feed/"]),
    # Dev / infra press
    _s("thenewstack.io", "The New Stack", "B", ["https://thenewstack.io/feed/"]),
    _s("devclass.com", "DevClass", "B", ["https://devclass.com/feed/"]),
    _s("phoronix.com", "Phoronix", "B", ["https://www.phoronix.com/rss.php"]),
    _s("lwn.net", "LWN.net", "B", ["https://lwn.net/headlines/rss"], authority=0.75),
    _s("infoworld.com", "InfoWorld", "B", ["https://www.infoworld.com/feed/"]),
    _s(
        "semianalysis.com",
        "SemiAnalysis",
        "B",
        ["https://www.semianalysis.com/feed"],
        paywall=True,
        authority=0.75,
    ),
    # ---- Tier C: company engineering blogs and the tail -------------------
    _s("blog.google", "Google Blog", "C", ["https://blog.google/rss/"], authority=0.6),
    _s(
        "blogs.microsoft.com",
        "Microsoft Blog",
        "C",
        ["https://blogs.microsoft.com/feed/"],
        authority=0.6,
    ),
    _s(
        "aws.amazon.com",
        "AWS News Blog",
        "C",
        ["https://aws.amazon.com/blogs/aws/feed/"],
        authority=0.6,
    ),
    _s("github.blog", "GitHub Blog", "C", ["https://github.blog/feed/"], authority=0.6),
    _s(
        "blog.cloudflare.com",
        "Cloudflare Blog",
        "C",
        ["https://blog.cloudflare.com/rss/"],
        authority=0.65,
    ),
    _s(
        "engineering.fb.com",
        "Meta Engineering",
        "C",
        ["https://engineering.fb.com/feed/"],
        authority=0.6,
    ),
    _s(
        "netflixtechblog.com",
        "Netflix Tech Blog",
        "C",
        ["https://netflixtechblog.com/feed"],
        authority=0.6,
    ),
    _s("stackoverflow.blog", "Stack Overflow Blog", "C", ["https://stackoverflow.blog/feed/"]),
    _s("omgubuntu.co.uk", "OMG! Ubuntu", "C", ["https://www.omgubuntu.co.uk/feed"]),
    _s("makeuseof.com", "MakeUseOf", "C", ["https://www.makeuseof.com/feed/"]),
    _s("howtogeek.com", "How-To Geek", "C", ["https://www.howtogeek.com/feed/"]),
    # Individual voices -- low volume, high signal.
    _s(
        "simonwillison.net",
        "Simon Willison",
        "C",
        ["https://simonwillison.net/atom/everything/"],
        authority=0.6,
    ),
    _s(
        "daringfireball.net",
        "Daring Fireball",
        "C",
        ["https://daringfireball.net/feeds/main"],
        authority=0.6,
    ),
    _s(
        "schneier.com",
        "Schneier on Security",
        "C",
        ["https://www.schneier.com/feed/atom/"],
        authority=0.7,
    ),
    _s(
        "martinfowler.com",
        "Martin Fowler",
        "C",
        ["https://martinfowler.com/feed.atom"],
        authority=0.65,
    ),
]
