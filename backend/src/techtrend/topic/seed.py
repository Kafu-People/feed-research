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
        "must": ["AI", "artificial intelligence", "LLM", "OpenAI", "Anthropic",
                 "ChatGPT", "Claude", "Gemini", "DeepSeek", "Mistral", "language model"],
        "should": ["model", "training", "benchmark", "reasoning", "agent", "inference"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Chips & semiconductors",
        "must": ["chip", "chips", "semiconductor", "GPU", "TSMC", "Nvidia", "wafer",
                 "foundry", "lithography", "ASML", "silicon"],
        "should": ["Intel", "AMD", "Qualcomm", "fab", "node", "export controls", "datacenter"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Cybersecurity",
        "must": ["vulnerability", "breach", "ransomware", "malware", "CVE",
                 "zero day", "exploit", "hacked", "phishing", "security flaw"],
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
        "must": ["SpaceX", "NASA", "rocket", "satellite", "orbit", "spacecraft",
                 "Starship", "lunar", "Mars"],
        "should": ["booster", "payload", "astronaut", "ESA", "reentry"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "EVs & batteries",
        "must": ["EV", "electric vehicle", "battery", "Tesla", "charging",
                 "lithium", "solid state battery"],
        "should": ["range", "gigafactory", "BYD", "Rivian", "charger"],
        "exclude": [],
        "entities": [],
    },
    {
        "title": "Big Tech regulation",
        "must": ["antitrust", "lawsuit", "regulator", "FTC", "DOJ", "European Commission",
                 "DMA", "fine", "settlement", "ruling", "judge"],
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
        "must": ["open source", "GitHub", "Linux", "Python", "Rust", "kernel",
                 "compiler", "developer tools"],
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
]
