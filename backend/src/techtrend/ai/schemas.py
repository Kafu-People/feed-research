"""Pydantic output models. Downstream code never parses a string."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StoryType = Literal[
    "original_reporting",
    "official_announcement",
    "analysis",
    "rewrite",
    "roundup",
    "routine_data",
    "speculation",
]


class Fact(BaseModel):
    kind: Literal["entity", "number", "date", "decision", "quote"]
    value: str
    normalized: str | None = Field(
        default=None, description="Canonical form: '1.2bn' -> '1200000000'"
    )


class JudgeResult(BaseModel):
    summary: str = Field(description="Exactly two sentences, in our own words.")
    story_type: StoryType
    facts: list[Fact] = Field(default_factory=list)
    novelty: float = Field(ge=0.0, le=1.0)
    novelty_rationale: str = ""


class TopicDraft(BaseModel):
    title: str
    must: list[str] = Field(default_factory=list)
    should: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    ambiguity: str | None = None
    options: list[str] = Field(default_factory=list)
