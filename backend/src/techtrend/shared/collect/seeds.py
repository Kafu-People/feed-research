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
    _s(
        "techcrunch.com",
        "TechCrunch",
        "A",
        [
            "https://techcrunch.com/feed/",
            # The venture desk. Probed 2026-09-07: the category feed's 16
            # items and the main feed's 20 shared not one headline, so the
            # funding stories are reachable here and, at that moment, only
            # here.
            "https://techcrunch.com/category/venture/feed/",
        ],
        authority=0.8,
    ),
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


# Remote work and the US job market. Two different kinds of source, kept
# apart because they behave differently downstream: WORK_TREND publishes
# articles (which group, summarise and answer questions like any other news),
# while JOB_BOARDS publish listings -- one item per open role, high volume,
# and nothing to "cluster" in the way a story clusters.
#
# Probed 2026-08-24 before adding. remote.co and flexjobs.com time out,
# remoteok.com 404s, and remoterocketship/builtin/shrm/wsj return 403 or 404 --
# all deliberately left out rather than added as endpoints that would park
# themselves after ten failures.
WORK_TREND: list[Seed] = [
    _s(
        "hiringlab.org",
        "Indeed Hiring Lab",
        "B",
        ["https://www.hiringlab.org/feed/"],
        # Indeed's own economists, publishing against Indeed's posting data --
        # the closest thing to a primary source for US hiring trends.
        authority=0.8,
    ),
    _s(
        "worklife.news",
        "WorkLife",
        "B",
        ["https://www.worklife.news/feed/"],
        authority=0.6,
    ),
    _s(
        "hrdive.com",
        "HR Dive",
        "B",
        ["https://www.hrdive.com/feeds/news/"],
        authority=0.65,
    ),
    _s(
        "hrexecutive.com",
        "HR Executive",
        "C",
        ["https://hrexecutive.com/feed/"],
        authority=0.55,
    ),
]

# Hacker News as the "feedback" half of the work topics -- first-person
# discussion rather than reporting. Reddit is the natural home for this and is
# unreachable: it rate-limits its RSS (429) AND its robots.txt blocks all
# crawlers, which the read stage obeys by production invariant. hnrss.org
# exposes HN as query feeds and is permissive.
#
# ONE seed entry, many feeds. hnrss.org previously appeared as a separate seed
# in two different groups; seed_sites dedupes sites by domain, so the seed
# count and the row count disagreed by one and test_seed_sites_is_idempotent
# failed. A site belongs to exactly one seed -- extra feeds go in this list.
#
# Query terms are chosen by PRECISION and probed before being added, because
# hnrss does not enforce quoted phrases. Dropped after probing: `"Surge AI"`
# and `"Scale AI"` (return "debt surge" and "at scale"), `"laid off"` and a
# bare `"job market"` on its own (returned rocket launches and a menu-bar app),
# and `"consulting rates"` (returned a rate-limiting library).
HN_VOICE: list[Seed] = [
    _s(
        "hnrss.org",
        "Hacker News",
        "B",
        [
            # return-to-office / US working conditions
            "https://hnrss.org/newest?q=%22return+to+office%22&count=25",
            # AI-training work and what it pays
            "https://hnrss.org/newest?q=%22data+annotation%22&count=25",
            "https://hnrss.org/newest?q=Mercor&count=25",
            "https://hnrss.org/newest?q=RLHF&count=25",
            # the developer market and contracting -- probed 2026-09-01
            "https://hnrss.org/newest?q=outsourcing&count=25",
            "https://hnrss.org/newest?q=nearshore&count=25",
            "https://hnrss.org/newest?q=%22junior+developers%22&count=25",
            "https://hnrss.org/newest?q=freelancing&count=25",
            # founders and investors -- probed 2026-09-07. `"Show HN"` was
            # tried and dropped: it returns every side project on the site,
            # which is a different topic from what founders are building as a
            # business. A bare `"seed round"` came back half funding
            # announcements and half unrelated headlines the query matched on
            # the comment text, so the money side leans on the two terms below.
            "https://hnrss.org/newest?q=%22startup+idea%22&count=25",
            "https://hnrss.org/newest?q=bootstrapped&count=25",
            "https://hnrss.org/newest?q=%22product+market+fit%22&count=25",
            "https://hnrss.org/newest?q=%22venture+capital%22&count=25",
        ],
        authority=0.55,
    ),
]

# The software labour market as a business: who is hiring engineers, what
# contract work pays, and how AI is changing both. Trade press plus the two
# newsletters that actually report on engineering hiring rather than opining
# about it.
#
# Probed 2026-09-01 with the production fetcher, so robots.txt and the real
# User-Agent applied. Left out after probing: cio.com (robots-blocked),
# staffingindustry.com and devinterrupted (403), shrm.org and getdx.com (404),
# labsnews.com (200 but zero entries). Contxto was added, probed on real
# output, and removed: 100 articles of Latin American fintech funding in mixed
# Spanish and English -- it would have flooded "AI models & labs", which posts
# to Slack, without serving this beat. Adding any of those would have created
# an endpoint that parks itself after ten failures.
DEV_MARKET: list[Seed] = [
    _s(
        "nearshoreamericas.com",
        "Nearshore Americas",
        "B",
        ["https://nearshoreamericas.com/feed/"],
        # The trade publication for this beat. Vendor-adjacent -- read its
        # market-size claims as interested, its hiring reporting as useful.
        authority=0.6,
    ),
    _s(
        "newsletter.pragmaticengineer.com",
        "The Pragmatic Engineer",
        "B",
        ["https://newsletter.pragmaticengineer.com/feed"],
        # Reports engineering hiring from primary sources rather than repeating
        # vendor reports -- the highest-authority source in this group.
        authority=0.75,
    ),
    _s(
        "leaddev.com",
        "LeadDev",
        "B",
        ["https://leaddev.com/rss.xml"],
        authority=0.6,
    ),
    _s(
        "infoq.com",
        "InfoQ",
        "B",
        ["https://feed.infoq.com/"],
        authority=0.6,
    ),
    _s(
        "refactoring.fm",
        "Refactoring",
        "C",
        ["https://refactoring.fm/feed"],
        authority=0.5,
    ),
    _s(
        "sloanreview.mit.edu",
        "MIT Sloan Management Review",
        "B",
        ["https://sloanreview.mit.edu/feed/"],
        authority=0.7,
    ),
    _s(
        "news.outsourceaccelerator.com",
        "Outsource Accelerator",
        "C",
        ["https://news.outsourceaccelerator.com/feed/"],
        # An outsourcing marketplace's own newsroom. Kept for coverage of a
        # beat nobody neutral reports on, at low authority for that reason.
        authority=0.45,
    ),
]


# Startups, funding and the people writing the cheques -- America and Europe.
# The existing corpus reports this beat only as a side-effect: probed over 90
# days, funding language ("seed round", "Series B", "led the round") appears in
# 126 articles, and 107 of them come from three sites -- SiliconANGLE,
# TechCrunch and The Next Web. European startup coverage is close to absent.
# A topic tuned against that corpus would be tuned against a rounding error.
#
# Probed 2026-09-07 with the production fetcher, so robots.txt and the real
# User-Agent applied. Left out after probing rather than added hopefully:
# tech.eu (robots-blocked -- the obvious European choice, and it says no),
# pitchbook.com and axios.com (403), fortune.com/section/venture and a16z.com
# (404), strictlyvc.com (200, newest entry dated 2019 -- a dead feed that
# answers), siliconcanals.com (200, but the feed carries syndicated psychology
# filler: "Psychology says people who feel a sense of calm in nature...").
VENTURE: list[Seed] = [
    # ---- Europe ----------------------------------------------------------
    _s(
        "sifted.eu",
        "Sifted",
        "B",
        ["https://sifted.eu/feed"],
        # FT-backed and the only European outlet on this beat with a newsroom
        # rather than a press-release pipeline. Metered, so Read stores the
        # preview and nothing more -- which is all the matcher reads anyway.
        paywall=True,
        authority=0.75,
    ),
    _s(
        "eu-startups.com",
        "EU-Startups",
        "B",
        ["https://www.eu-startups.com/feed/"],
        authority=0.6,
    ),
    _s(
        "uktech.news",
        "UKTN",
        "B",
        ["https://www.uktech.news/feed"],
        authority=0.6,
    ),
    _s(
        "techfundingnews.com",
        "Tech Funding News",
        "C",
        ["https://techfundingnews.com/feed/"],
        # Announcement-led: it reports the round, rarely the story behind it.
        # Useful for coverage of European raises nobody else writes up, at the
        # authority that implies.
        authority=0.45,
    ),
    _s(
        "maddyness.com",
        "Maddyness UK",
        "C",
        ["https://www.maddyness.com/uk/feed/"],
        # The English edition. The French one is the bigger publication and is
        # deliberately not seeded: the pipeline is English-only.
        authority=0.5,
    ),
    _s(
        "arcticstartup.com",
        "ArcticStartup",
        "C",
        ["https://arcticstartup.com/feed/"],
        # Nordic and Baltic raises, which the London- and Berlin-centred
        # outlets above mostly skip.
        authority=0.5,
    ),
    # ---- America ---------------------------------------------------------
    _s(
        "news.crunchbase.com",
        "Crunchbase News",
        "B",
        ["https://news.crunchbase.com/feed/"],
        # Written against Crunchbase's own deal data -- the closest thing to a
        # primary source for US venture funding, the way Hiring Lab is for
        # hiring.
        authority=0.7,
    ),
]

# Analysis rather than announcement: market sizing, category deep-dives, and
# founders writing about what they built and why. This is the half of the beat
# that dates slowly -- a funding round is news for a day, "why vertical SaaS
# margins are different" is worth reading a month later.
#
# Probed 2026-09-07. Left out: every.to and indiehackers.com (200 with zero
# parseable entries), sacra.com and starterstory.com (404), feld.com (200, but
# the feed is a personal blog -- home-automation dashboards and book reviews),
# bothsidesofthetable.com (zero entries), dealroom.co/blog (zero entries).
ANALYSIS: list[Seed] = [
    _s(
        "cbinsights.com",
        "CB Insights Research",
        "B",
        ["https://www.cbinsights.com/research/feed/"],
        # A research firm's own newsroom: market maps, category sizing, and
        # the interviews that go with them. Interested in selling reports --
        # read its market-size numbers the way Nearshore Americas' are read.
        authority=0.6,
    ),
    _s(
        "stratechery.com",
        "Stratechery",
        "B",
        ["https://stratechery.com/feed/"],
        paywall=True,
        authority=0.75,
    ),
    _s(
        "ben-evans.com",
        "Benedict Evans",
        "C",
        ["https://www.ben-evans.com/benedictevans?format=rss"],
        authority=0.7,
    ),
    _s(
        "tomtunguz.com",
        "Tomasz Tunguz",
        "C",
        ["https://tomtunguz.com/index.xml"],
        # A VC writing from data rather than from theses. Two entries in the
        # feed at probe time -- low volume, and that is the point.
        authority=0.6,
    ),
    _s(
        "lennysnewsletter.com",
        "Lenny's Newsletter",
        "C",
        ["https://www.lennysnewsletter.com/feed"],
        authority=0.55,
    ),
    _s(
        "saastr.com",
        "SaaStr",
        "C",
        ["https://www.saastr.com/feed/"],
        # Founder-to-founder operating advice. Opinionated and repetitive by
        # design; seeded low so it loses ties against reporting.
        authority=0.45,
    ),
    _s(
        "ycombinator.com",
        "Y Combinator",
        "C",
        ["https://www.ycombinator.com/blog/rss"],
        # An accelerator talking about itself, which is still the primary
        # source for what it is funding.
        authority=0.55,
    ),
]
