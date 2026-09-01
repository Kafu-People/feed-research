"""The ten hand-written keyword lists -- M3's isolation instrument.

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
]
