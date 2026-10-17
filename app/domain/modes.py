"""Deterministic mode signals and precedence (FR-2.2, FR-2.3, FR-2.4)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from app.domain.checking import normalize

SUPPORT_TERMS = frozenset(
    {
        "sad",
        "scared",
        "afraid",
        "cry",
        "crying",
        "hurt",
        "hurts",
        "mean",
        "worried",
        "worry",
        "lonely",
        "alone",
        "unhappy",
        "cant",
        "i cant",
        "dont want to",
        "dont want",
    }
)
STORY_TERMS = frozenset({"story", "stories", "tale", "tales"})
PLAY_TERMS = frozenset({"play", "game", "games", "pretend"})
LEARN_TERMS = frozenset({"teach", "quiz", "learn", "lesson", "practice", "spell"})
LOW_EFFORT_TERMS = frozenset({"idk", "no", "boring", "bored", "meh", "nah"})
UNSURE_TERMS = frozenset({"idk", "dunno", "unsure", "dont know", "not sure"})
SEVERE_DISTRESS_TERMS = frozenset(
    {
        "want to die",
        "wanna die",
        "kill myself",
        "kill me",
        "hurt myself",
        "end my life",
        "suicide",
    }
)


@dataclass(frozen=True)
class Signals:
    support: bool
    wants_story: bool
    wants_play: bool
    wants_learning: bool
    low_effort: bool
    unsure: bool
    severe_distress: bool


def _has_any(text: str, terms: frozenset[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None for term in terms)


def detect_signals(text: str) -> Signals:
    """Return deterministic mode signals for one child message."""

    normalised = normalize(text)
    return Signals(
        support=_has_any(normalised, SUPPORT_TERMS),
        wants_story=_has_any(normalised, STORY_TERMS),
        wants_play=_has_any(normalised, PLAY_TERMS),
        wants_learning=_has_any(normalised, LEARN_TERMS),
        low_effort=_has_any(normalised, LOW_EFFORT_TERMS),
        unsure=_has_any(normalised, UNSURE_TERMS),
        severe_distress=_has_any(normalised, SEVERE_DISTRESS_TERMS),
    )


Mode = Literal["learning", "conversation", "engagement", "support"]
DecisionMode = Literal["learning", "conversation", "engagement", "support", "auto"]
ALL_MODES: tuple[Mode, ...] = ("learning", "conversation", "engagement", "support")
SUGGESTION_MIN_CONFIDENCE = 0.5


class ModeSettings(Protocol):
    max_learning_streak: int


@dataclass(frozen=True)
class ModeDecision:
    mode: DecisionMode
    allowed_modes: tuple[Mode, ...]
    allows_new_item: bool


def decide_mode(
    signals: Signals,
    has_pending_attempt: bool,
    learning_streak: int,
    settings: ModeSettings,
) -> ModeDecision:
    """Apply the seven-row precedence table; `auto` delegates the choice to the LLM."""

    if signals.support:
        return ModeDecision("support", ("support",), False)
    if has_pending_attempt:
        return ModeDecision("learning", ("learning",), True)
    if signals.wants_story or signals.wants_play:
        return ModeDecision("engagement", ("engagement",), False)
    if signals.wants_learning:
        return ModeDecision("learning", ("learning",), True)

    allowed: tuple[Mode, ...] = ALL_MODES
    if learning_streak >= settings.max_learning_streak:
        allowed = tuple(mode for mode in ALL_MODES if mode != "learning")
    return ModeDecision("auto", allowed, "learning" in allowed)


def validate_suggestion(
    suggested_mode: str | None,
    confidence: float,
    allowed_modes: Sequence[Mode],
) -> Mode:
    """Accept an LLM suggestion only from the allowed set with confidence >= 0.5."""

    if (
        suggested_mode is not None
        and suggested_mode in allowed_modes
        and confidence >= SUGGESTION_MIN_CONFIDENCE
    ):
        return cast(Mode, suggested_mode)
    return "conversation"
