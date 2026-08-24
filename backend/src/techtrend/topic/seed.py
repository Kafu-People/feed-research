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
        "should": [
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
        # Open positions from the remote job boards.
        #
        # NOTE: the matcher reads title + description ONLY, never the body.
        # Board descriptions are boilerplate ("X is hiring a remote Y to join
        # their remote Z team") -- they always contain "remote" and never
        # contain the country or the hybrid caveat that would disqualify a
        # role. So `exclude` fires only on the rare listing that says "hybrid"
        # in its title. Measured, not assumed: see the precision figures in the
        # commit message.
        "title": "Fully remote jobs",
        "must": ["remote"],
        "should": [
            "united states",
            "usa",
            "americas",
            "engineer",
            "developer",
            "designer",
            "manager",
        ],
        "exclude": ["hybrid", "on-site", "onsite", "in-office"],
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
]
