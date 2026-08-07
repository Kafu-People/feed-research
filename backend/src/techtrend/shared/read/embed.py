"""The pluggable embedding provider.

One field, three downstream jobs: Group (same-event candidates), Match
(paraphrase recall), Judge (the 30-day novelty window). The model choice is
SEMI-PERMANENT -- changing it invalidates every stored vector, so a swap is a
corpus-wide re-embed, not a config flip.

Current model: BAAI/bge-small-en-v1.5 via fastembed -- 384 dims, ~34MB,
fast on CPU. Chosen to run comfortably on a small VPS; upgrading later is
cheap while the corpus is thousands, not millions.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from techtrend.platform.config import settings

DIMS = 384


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    """Lazy: the ONNX model loads on first use, once per process."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [v.tolist() for v in model.embed(texts)]  # type: ignore[attr-defined]


class FakeEmbedder:
    """Deterministic, dependency-free vectors for tests.

    Word-hash based so that texts sharing words get high cosine similarity --
    enough signal for clustering tests to be meaningful.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * DIMS
            for w in t.lower().split():
                v[hash(w) % DIMS] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


_embedder: Embedder | None = None


def embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = settings()
        _embedder = FakeEmbedder() if s.embedding_fake else FastEmbedder(s.embedding_model)
    return _embedder


async def embed_async(texts: list[str]) -> list[list[float]]:
    """ONNX inference is CPU-bound; keep it off the event loop."""
    return await asyncio.to_thread(embedder().embed, texts)


def embedding_input(title: str, body_text: str | None) -> str:
    """Title carries most of the signal; the lede grounds it. A metadata-only
    (paywalled) article embeds from its title alone and remains first-class."""
    if not body_text:
        return title
    return f"{title}\n{body_text[:1000]}"
