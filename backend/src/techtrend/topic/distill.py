"""Sentence -> keyword list. The topic layer's doorway to the AI layer.

api/ may not import techtrend.ai directly; it reaches the distiller through
here (api -> topic -> ai), which the layer contract permits.
"""

from __future__ import annotations

from techtrend.ai.client import client
from techtrend.ai.schemas import TopicDraft


async def distill(sentence: str) -> TopicDraft:
    return await client().distill(sentence)
