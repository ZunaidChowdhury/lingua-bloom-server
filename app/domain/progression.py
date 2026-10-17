"""Deterministic level progression with no demotion (FR-1.4, FR-1.5)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.domain.checking import AttemptResult

TOP_LEVEL = 3


class ProgressSettings(Protocol):
    progress_window: int
    progress_required_correct: int
    progress_min_distinct_skills: int


@dataclass(frozen=True)
class CountedAttempt:
    """One counted attempt: the first attempt on an item exposure."""

    skill: str
    correct: bool


@dataclass(frozen=True)
class ProgressDecision:
    current_level: int
    next_level: int
    leveled_up: bool
    mastered: bool
    reset_window: bool
    correct_in_window: int
    distinct_skills: int


def evaluate_progress(
    counted_attempts: Sequence[CountedAttempt],
    level: int,
    settings: ProgressSettings,
) -> ProgressDecision:
    """Decide whether the child levels up. A single mistake never demotes."""

    window = list(counted_attempts)[-settings.progress_window:]
    correct_in_window = sum(1 for attempt in window if attempt.correct)
    distinct_skills = len({attempt.skill for attempt in window if attempt.correct})
    threshold_met = (
        correct_in_window >= settings.progress_required_correct
        and distinct_skills >= settings.progress_min_distinct_skills
    )

    if level >= TOP_LEVEL:
        return ProgressDecision(
            current_level=TOP_LEVEL,
            next_level=TOP_LEVEL,
            leveled_up=False,
            mastered=threshold_met,
            reset_window=False,
            correct_in_window=correct_in_window,
            distinct_skills=distinct_skills,
        )

    next_level = level + 1 if threshold_met else level
    return ProgressDecision(
        current_level=level,
        next_level=next_level,
        leveled_up=threshold_met,
        mastered=False,
        reset_window=threshold_met,
        correct_in_window=correct_in_window,
        distinct_skills=distinct_skills,
    )


Action = Literal["advance", "retry", "hint", "reveal"]


class AttemptSettings(Protocol):
    hint_after_misses: int
    reveal_after_misses: int


@dataclass(frozen=True)
class AttemptDecision:
    action: Action
    counted: bool
    clears_pending: bool
    miss_count: int


def apply_attempt(
    pending_attempts: int,
    result: AttemptResult,
    settings: AttemptSettings,
) -> AttemptDecision:
    """Map one attempt to the next action. Only the first attempt is counted."""

    first_attempt = pending_attempts == 0

    if result.reason == "correct":
        return AttemptDecision("advance", first_attempt, True, pending_attempts)

    if result.reason in ("unsure", "skipped"):
        return AttemptDecision("retry", False, False, pending_attempts)

    misses = pending_attempts + 1
    if misses >= settings.reveal_after_misses:
        return AttemptDecision("reveal", False, True, misses)
    if misses >= settings.hint_after_misses:
        return AttemptDecision("hint", False, False, misses)
    return AttemptDecision("retry", first_attempt, False, misses)
