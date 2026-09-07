"""The hand-written keyword lists -- M3's isolation instrument.

Hand-written lists isolate the matcher from the (future) distiller: a bad
feed has exactly one possible cause. These are also perfectly usable topics
for a first real user.
"""

from __future__ import annotations

from typing import TypedDict


class SeedTopic(TypedDict):
    title: str
    must: list[str]
    should: list[str]
    exclude: list[str]
    entities: list[str]


TOPICS: list[SeedTopic] = [
    {
        "title": "AI models & labs",
        "must": [
            "AI",
            "artificial intelligence",
            "LLM",
            "OpenAI",
            "Anthropic",
            "ChatGPT",
            "Claude",
            "Gemini",
            "DeepSeek",
            "Mistral",
            "language model",
        ],
        "should": ["model", "training", "benchmark", "reasoning", "agent", "inference"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Chips & semiconductors",
        "must": [
            "chip",
            "chips",
            "semiconductor",
            "GPU",
            "TSMC",
            "Nvidia",
            "wafer",
            "foundry",
            "lithography",
            "ASML",
            "silicon",
        ],
        "should": ["Intel", "AMD", "Qualcomm", "fab", "node", "export controls", "datacenter"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Cybersecurity",
        "must": [
            "vulnerability",
            "breach",
            "ransomware",
            "malware",
            "CVE",
            "zero day",
            "exploit",
            "hacked",
            "phishing",
            "security flaw",
        ],
        "should": ["patch", "attacker", "credentials", "backdoor", "botnet"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Apple ecosystem",
        "must": ["Apple", "iPhone", "iPad", "macOS", "iOS", "AirPods", "MacBook", "watchOS"],
        "should": ["App Store", "Siri", "Tim Cook", "Vision Pro", "M5", "firmware"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Space & launch",
        "must": [
            "SpaceX",
            "NASA",
            "rocket",
            "satellite",
            "orbit",
            "spacecraft",
            "Starship",
            "lunar",
            "Mars",
        ],
        "should": ["booster", "payload", "astronaut", "ESA", "reentry"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "EVs & batteries",
        "must": [
            "EV",
            "electric vehicle",
            "battery",
            "Tesla",
            "charging",
            "lithium",
            "solid state battery",
        ],
        "should": ["range", "gigafactory", "BYD", "Rivian", "charger"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Big Tech regulation",
        "must": [
            "antitrust",
            "lawsuit",
            "regulator",
            "FTC",
            "DOJ",
            "European Commission",
            "DMA",
            "fine",
            "settlement",
            "ruling",
            "judge",
        ],
        "should": ["Google", "Meta", "Apple", "Amazon", "Microsoft", "appeal", "monopoly"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Gaming",
        "must": ["game", "gaming", "PlayStation", "Xbox", "Nintendo", "Steam", "console"],
        "should": ["Switch", "GPU", "esports", "studio", "release date"],
        "exclude": ["gambling"],
        "entities": [],
    },
    {
        "title": "Open source & dev tools",
        "must": [
            "open source",
            "GitHub",
            "Linux",
            "Python",
            "Rust",
            "kernel",
            "compiler",
            "developer tools",
        ],
        "should": ["maintainer", "license", "repository", "release", "framework"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Streaming & media",
        "must": ["Netflix", "streaming", "YouTube", "Spotify", "Disney", "HBO", "podcast"],
        "should": ["subscriber", "ad tier", "content", "series", "movie"],
        "exclude": [],
        "entities": [],
    },
    {
        # Trend and analysis about work and the US labour market. Ordinary
        # articles: these group, summarise and answer questions like any story.
        "title": "Remote work & US job market",
        "must": [
            "remote work",
            "return to office",
            "job market",
            "labor market",
            "labour market",
            "hiring",
            "layoffs",
            "unemployment",
            "job postings",
            "workforce",
            "hybrid work",
            "four-day week",
        ],
        # US terms sit in `should`, not in `entities`. `entities` is an AND
        # gate, and only 18% of matches name the country in title/description
        # -- Indeed's own "Labor Market Snapshot" does, an HR Dive piece on US
        # employment law often does not. Gating on it would drop most of the
        # feed to enforce something the source list already largely enforces:
        # Hiring Lab, HR Dive and HR Executive are US publications.
        "should": [
            "US",
            "U.S.",
            "United States",
            "American",
            "remote",
            "employment",
            "recruiting",
            "talent",
            "wages",
            "salary",
            "employees",
            "office",
            "workers",
        ],
        "exclude": [],
        "entities": [],
    },
    {
        # The people doing AI-training work, and what it pays -- distinct from
        # topic 13, which is AI training as a technical/industry story. This is
        # the contributor side: who is hiring annotators and evaluators, what
        # the hourly rates are, what the work is actually like.
        #
        # "Appen" and "Micro1" are safe as must-terms despite looking like
        # substrings: the matcher uses word-boundary matching, so "appen" does
        # not fire on "happened".
        "title": "AI training work & pay",
        # RLHF and "annotator" were must-terms in the first cut and pulled in
        # ML research -- "A Scalable RLHF Trainer", "Replacing RLHF with
        # Entropic Loss". That is topic 3's subject, not this one. They are
        # `should` now: they raise a score that a work-term already qualified.
        "must": [
            "data annotation",
            "AI trainer",
            "AI training job",
            "AI training work",
            "Mercor",
            "DataAnnotation",
            "Surge AI",
            "Scale AI",
            "Handshake AI",
            "Micro1",
            "Toloka",
            "Appen",
            "Mechanical Turk",
        ],
        "should": [
            "hourly rate",
            "per hour",
            "pay",
            "earn",
            "salary",
            "contributor",
            "freelance",
            "gig",
            "contractor",
            "evaluator",
            "annotator",
            "RLHF",
            "coding",
            "expert",
        ],
        "exclude": [],
        "entities": [],
    },
    {
        # The developer labour market itself. Terms are deliberately SPECIFIC:
        # probed against 15k live articles, broad words ("talent", "career",
        # "jobs", "contractor") match mostly on the publisher's description of
        # an unrelated story, so they cost far more precision than they buy.
        #
        # `entities` is the AND gate -- a story must carry a job word AND a
        # software word. Without it, "U.S. BLS revision erases thousands of
        # jobs" lands here instead of in "Remote work & US job market" (18).
        "title": "Dev job market & the AI shakeout",
        "must": [
            "hiring",
            "rehiring",
            "layoffs",
            "laid off",
            "job market",
            "jobs market",
            "job seekers",
            "hiring managers",
            "junior engineer",
            "junior engineers",
            "junior developer",
            "junior developers",
            "entry-level",
            "headcount",
            "hiring freeze",
        ],
        "should": [
            "AI",
            "junior",
            "senior",
            "graduate",
            "salary",
            "demand",
            "automation",
            "career",
            "team",
            "productivity",
        ],
        "exclude": [],
        "entities": [
            "engineer",
            "engineers",
            "developer",
            "developers",
            "software",
            "engineering",
            "programmer",
            "programmers",
            "coding",
            "IT",
        ],
    },
    {
        # The supply side: software work sold across borders. These must-terms
        # are unambiguous enough not to need an entity gate -- "nearshore" and
        # "BPO" mean one thing. Bare "offshore" is NOT here: it matched wind
        # farms and drilling, so the phrase forms are used and the exclude
        # catches the rest.
        "title": "Outsourcing, nearshore & dev agencies",
        "must": [
            "nearshore",
            "nearshoring",
            "outsourcing",
            "outsourced",
            "offshoring",
            "offshore development",
            "offshore delivery",
            "BPO",
            "business process outsourcing",
            "call center",
            "call centre",
            "staff augmentation",
            "IT services",
            "delivery center",
            "delivery hub",
            "freelancing",
            "software agency",
            "dev shop",
        ],
        "should": [
            "AI",
            "Latin America",
            "LatAm",
            "Brazil",
            "Mexico",
            "India",
            "Philippines",
            "client",
            "hourly rate",
            "contract",
            "talent",
            "margin",
        ],
        "exclude": ["offshore wind", "offshore drilling", "offshore oil"],
        "entities": [],
    },
    {
        # What founders are building and how -- the idea end of the beat, not
        # the money end (that is the next topic). Lives almost entirely on
        # Hacker News, Lenny's and the YC blog: over 120 days and 18,971 live
        # articles, the existing news corpus produced ZERO stories above 0.6
        # and exactly one above 0.55, because trade press reports funding and
        # product launches, not idea validation. The new sources carry it --
        # 11 of the 321 items in one pull of them cleared 0.6.
        #
        # `must` is phrases only. "founder" and "startup" are `should`: as
        # must-terms they matched every story that merely NAMES a founder --
        # "Investors sue Selena Gomez", "Arm co-founder's AI warning",
        # "Laboratoria Founder Is Increasing Women in Tech" -- which is a
        # person, not a playbook. Same for "Y Combinator" and "YC", which on
        # their own returned YC's partner-hire announcements.
        #
        # "accelerator", "incubator", "MVP" and "side project" were probed and
        # dropped: 16 of "accelerator"'s 19 hits are AI silicon or CERN's
        # particle accelerator, "MVP" hit nothing real, "incubator" hit a
        # Photoshop feature, "side project" hit nothing at all.
        "title": "Startup ideas & founder playbooks",
        "must": [
            "startup idea",
            "startup ideas",
            "bootstrapped",
            "bootstrapping",
            "solo founder",
            "indie hacker",
            "product market fit",
            "founder mode",
            "early-stage startup",
            "first customers",
            "paying customers",
            "customer discovery",
            "go to market",
            "build in public",
            "ramen profitable",
            "micro saas",
            "side business",
            "niche market",
        ],
        "should": [
            "founder",
            "founders",
            "co-founder",
            "startup",
            "Y Combinator",
            "YC",
            "revenue",
            "customers",
            "ARR",
            "MRR",
            "SaaS",
            "growth",
            "pivot",
            "idea",
            "launch",
            "Europe",
            "European",
            "US",
            "American",
        ],
        "exclude": [],
        # The AND gate: an idea word AND something being built as a business.
        # Without it "bootstrapped" matched "Nix has a source-bootstrapped
        # OpenJDK", which is the same word about a compiler.
        "entities": [
            "startup",
            "startups",
            "founder",
            "founders",
            "co-founder",
            "company",
            "companies",
            "business",
            "product",
            "customers",
        ],
    },
    {
        # The money: rounds, funds, and the investors writing the cheques,
        # across America and Europe.
        #
        # Region words are `should`, not `entities`, for the reason topic 18
        # states and this one re-measures: of the 110 stories this topic puts
        # above the floor, 46% name a US or European place in title or
        # description. An AND gate on region would delete the other 54% --
        # "Wispr raises $280M at $2B valuation" says nothing about where Wispr
        # is -- to enforce something the source list already enforces, since
        # Sifted, EU-Startups, UKTN, Maddyness, ArcticStartup, Crunchbase News
        # and TechCrunch's venture desk are American and European publications.
        #
        # Measured across both corpora (19,293 items): 110 above 0.6 -- 87 of
        # them 0.72/day of the existing corpus, the rest from the new venture
        # sources -- and a random 35 of those read one false positive (a
        # Schneier post that used "raised" in its description). That precision
        # is what earns bare "raises" and "raised" a place in `must` -- they
        # are broad words, but the entity gate below means they only count
        # alongside money or a company.
        "title": "Startup funding & investors",
        "must": [
            "venture capital",
            "seed round",
            "pre-seed",
            "Series A",
            "Series B",
            "Series C",
            "Series D",
            "funding round",
            "led the round",
            "term sheet",
            "limited partner",
            "angel investor",
            "venture fund",
            "spinout",
            "raises",
            "raised",
            "valuation",
            "oversubscribed",
            "first close",
            "closes its fund",
            "growth round",
            "down round",
            "cap table",
        ],
        "should": [
            "million",
            "billion",
            "investor",
            "investors",
            "startup",
            "fund",
            "venture",
            "portfolio",
            "VC",
            "Europe",
            "European",
            "US",
            "American",
            "London",
            "Berlin",
            "Paris",
            "Silicon Valley",
            "New York",
        ],
        "exclude": [],
        "entities": [
            "startup",
            "startups",
            "founder",
            "founders",
            "investor",
            "investors",
            "venture",
            "fund",
            "funding",
            "round",
            "million",
            "billion",
            "valuation",
            "capital",
            "backed",
        ],
    },
    {
        # Sizing a field rather than reporting an event: how big a market is,
        # who holds what share of it, what it is paying, and where demand is
        # going.
        #
        # This is the hardest of the three to express in keywords, and the
        # lists say so honestly. Analysis PROSE is not lexically identifiable
        # -- Benedict Evans files "AI, tools and transformation" and Stratechery
        # files "Friction and Feedback", and no keyword list reaches either.
        # What IS identifiable is a market being MEASURED, so the terms are
        # measurement words, and the topic catches the analysis publications
        # only when they put a number on something ("Ways to think about token
        # pricing" scores 0.60 on supply, demand and pricing).
        #
        # Dropped after probing: "estimates", "outlook", "revenue growth" and
        # "market cap" -- they turned the topic into an earnings wire, matching
        # "Airbnb stock soars 9% on earnings beat" ahead of any field analysis.
        # "deep dive" (7 hits, all Kingdom Hearts and GTA VI), "vertical" (tab
        # bars), "moat" and "benchmark" (AI benchmarks) went the same way.
        "title": "Market & sector analysis",
        "must": [
            "market analysis",
            "market research",
            "market size",
            "market share",
            "market map",
            "market opportunity",
            "market leader",
            "total addressable market",
            "TAM",
            "competitive landscape",
            "unit economics",
            "business model",
            "margins",
            "adoption",
            "demand",
            "pricing",
            "forecast",
            "analyst",
            "analysts",
            "survey",
            "study finds",
            "report finds",
            "spending",
        ],
        "should": [
            "market",
            "industry",
            "sector",
            "category",
            "growth",
            "data",
            "report",
            "customers",
            "share",
            "trend",
            "revenue",
            "buyers",
            "vertical",
            "incumbents",
            "fintech",
            "robotics",
            "climate tech",
            "Europe",
            "European",
            "US",
            "American",
        ],
        "exclude": [],
        # The AND gate is what keeps this a MARKET topic. Without it the same
        # must-terms matched "UNICEF study finds 60% of online child sexual
        # abuse happens on social media" -- a study, and no market in sight.
        "entities": [
            "market",
            "markets",
            "industry",
            "industries",
            "sector",
            "sectors",
            "category",
            "segment",
            "economy",
            "customers",
            "revenue",
            "sales",
            "buyers",
            "demand",
            "adoption",
        ],
    },
]
