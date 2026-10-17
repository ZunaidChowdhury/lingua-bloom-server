"""Social and emotional learning: check-ins, support playbook, feedback (FR-3.1-FR-3.6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.domain.modes import Mode

Mood = Literal["positive", "neutral", "low"]


@dataclass(frozen=True)
class Feeling:
    id: str
    emoji: str
    mood: Mood
    routes_to_support: bool


FEELINGS: tuple[Feeling, ...] = (
    Feeling("happy", "\U0001F60A", "positive", False),
    Feeling("excited", "\U0001F929", "positive", False),
    Feeling("sleepy", "\U0001F634", "neutral", False),
    Feeling("worried", "\U0001F61F", "low", True),
    Feeling("sad", "\U0001F622", "low", True),
)
FEELINGS_BY_ID: dict[str, Feeling] = {feeling.id: feeling for feeling in FEELINGS}


class CheckinSettings(Protocol):
    checkin_every_n_turns: int


def checkin_due(
    turns_since_checkin: int,
    has_pending_item: bool,
    mode: Mode,
    settings: CheckinSettings,
) -> bool:
    """A check-in is due on cadence, unless the child is mid-item or in Support."""

    if has_pending_item or mode == "support":
        return False
    return turns_since_checkin >= settings.checkin_every_n_turns


@dataclass(frozen=True)
class FeelingChoice:
    id: str
    emoji: str
    label: str


@dataclass(frozen=True)
class FeelingCheckin:
    type: Literal["feeling_checkin"]
    choices: tuple[FeelingChoice, ...]


def feeling_checkin() -> FeelingCheckin:
    """The tap-to-answer activity shared with the API and the UI."""

    return FeelingCheckin(
        type="feeling_checkin",
        choices=tuple(FeelingChoice(f.id, f.emoji, f.id.capitalize()) for f in FEELINGS),
    )


SUPPORT_CHOICES = ("rest", "chat", "easier_game")


@dataclass(frozen=True)
class SupportPlaybook:
    acknowledge: str
    gentle_step: str
    choices: tuple[str, ...]


_PLAYBOOKS: dict[int, SupportPlaybook] = {
    1: SupportPlaybook("I am here with you.", "Let us take one slow breath.", SUPPORT_CHOICES),
    2: SupportPlaybook(
        "Thank you for telling me.",
        "Let us breathe in slowly together.",
        SUPPORT_CHOICES,
    ),
    3: SupportPlaybook(
        "Thank you for sharing how you feel.",
        "Let us try a slow, calm breath together.",
        SUPPORT_CHOICES,
    ),
}


def support_steps(level: int) -> SupportPlaybook:
    """Acknowledge, one gentle step, then a rest/chat/easier-game choice. Never a quiz."""

    if level <= 1:
        return _PLAYBOOKS[1]
    if level == 2:
        return _PLAYBOOKS[2]
    return _PLAYBOOKS[3]


BANNED_FEEDBACK_WORDS = frozenset({"wrong", "bad", "fail", "stupid"})

EFFORT_PRAISE: tuple[str, ...] = (
    "Nice try!",
    "You kept trying.",
    "Great effort!",
    "I like how you tried.",
)
TRY_AGAIN_LINE = "Let us try again together."
