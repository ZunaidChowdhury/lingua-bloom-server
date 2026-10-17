"""Pydantic models for the curriculum bank (pure domain, no I/O)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemType = Literal["choice", "word", "fill_blank", "sentence"]
Level = Literal[1, 2, 3]


class Choice(BaseModel):
    """One tappable option; `id` is a stable key, never shown as the answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    emoji: str | None = None


class Answer(BaseModel):
    """Server-only answer key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice_id: str | None = None
    accepted_words: list[str] = Field(default_factory=list)


class Rubric(BaseModel):
    """Server-only rubric for `sentence` items (ARCHITECTURE 6.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_words: int = Field(ge=1)
    max_words: int = Field(ge=1)
    keyword_groups: list[list[str]] = Field(default_factory=list)
    pattern: str | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> Rubric:
        if self.max_words < self.min_words:
            raise ValueError("max_words must be greater than or equal to min_words")
        return self


class Item(BaseModel):
    """One curriculum item (ARCHITECTURE 6.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    level: Level
    skill: str
    type: ItemType
    prompt: str
    emoji: str | None = None
    choices: list[Choice] = Field(default_factory=list)
    answer: Answer | None = None
    rubric: Rubric | None = None
    hint: str
    reveal: str


class PublicChoice(BaseModel):
    """Child-facing option; carries no correctness information."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    emoji: str | None = None


class PublicItem(BaseModel):
    """The only shape of an item allowed to leave the server."""

    model_config = ConfigDict(frozen=True)

    id: str
    level: Level
    skill: str
    type: ItemType
    prompt: str
    emoji: str | None = None
    choices: list[PublicChoice] = Field(default_factory=list)
    hint: str


def public_view(item: Item) -> PublicItem:
    """Return child-facing fields only: no answer key, accepted words, rubric, or reveal."""

    return PublicItem(
        id=item.id,
        level=item.level,
        skill=item.skill,
        type=item.type,
        prompt=item.prompt,
        emoji=item.emoji,
        choices=[PublicChoice(id=c.id, label=c.label, emoji=c.emoji) for c in item.choices],
        hint=item.hint,
    )
