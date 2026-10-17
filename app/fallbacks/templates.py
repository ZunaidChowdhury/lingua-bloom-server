"""Deterministic, level-appropriate fallback replies used when the LLM fails (FR-5.4)."""

from __future__ import annotations

from typing import Literal

from app.domain.modes import Mode

Event = Literal[
    "greeting",
    "correct",
    "incorrect",
    "hint",
    "reveal",
    "level_up",
    "break_offer",
    "checkin",
    "support",
    "distress",
    "generic",
]

EVENT_MODES: dict[Event, tuple[Mode, ...]] = {
    "greeting": ("learning", "conversation", "engagement", "support"),
    "correct": ("learning",),
    "incorrect": ("learning",),
    "hint": ("learning",),
    "reveal": ("learning",),
    "level_up": ("learning",),
    "break_offer": ("learning",),
    "checkin": ("conversation", "engagement"),
    "support": ("support",),
    "distress": ("support",),
    "generic": ("learning", "conversation", "engagement", "support"),
}

TEMPLATES: dict[Event, dict[int, tuple[str, ...]]] = {
    "greeting": {
        1: ("Hi {nickname}!", "Hello {nickname}."),
        2: ("Hi {nickname}, good to see you!", "Hello {nickname}, let us begin."),
        3: ("Hi {nickname}, good to see you again!", "Hello {nickname}, ready to explore?"),
    },
    "correct": {
        1: ("Yes! Well done.", "That is right!"),
        2: ("Yes, that is correct!", "Well done, you got it!"),
        3: ("That is correct, nicely done!", "Correct! You are doing great!"),
    },
    "incorrect": {
        1: ("Nice try! Let us try again.", "Good try. Let us see."),
        2: ("Nice try! Let us try again together.", "Good effort. Let us try once more."),
        3: ("Nice try! Let us work it out together.", "Good effort. Let us try that again."),
    },
    "hint": {
        1: ("Here is a little hint.", "A small clue for you."),
        2: ("Here is a hint to help you.", "Let me give you a small clue."),
        3: ("Here is a hint to guide you.", "Let me offer a gentle clue."),
    },
    "reveal": {
        1: ("The answer is here. Let us look.", "Here is the answer. Good try."),
        2: (
            "Here is the answer. Let us look together.",
            "The answer is here. You did well trying.",
        ),
        3: (
            "Here is the answer. Let us see it together.",
            "Let us look at the answer together.",
        ),
    },
    "level_up": {
        1: ("Hooray {nickname}! You grew!", "Well done {nickname}! You moved up!"),
        2: (
            "Hooray {nickname}! You reached a new level!",
            "Well done {nickname}! You leveled up!",
        ),
        3: ("Hooray {nickname}! You are blooming!", "Well done {nickname}! Another step up!"),
    },
    "break_offer": {
        1: ("Let us take a little break.", "Shall we play now?"),
        2: ("Let us take a short break together.", "Shall we do something fun now?"),
        3: ("Let us pause and take a short break.", "Shall we try something fun for a while?"),
    },
    "checkin": {
        1: ("How do you feel today?", "How are you feeling?"),
        2: ("How are you feeling today?", "Tell me how you feel today."),
        3: ("How are you feeling today, {nickname}?", "Would you like to share how you feel?"),
    },
    "support": {
        1: ("I am here with you.", "It is okay to feel this way."),
        2: (
            "I am here with you. Let us take a slow breath.",
            "It is okay to feel this way. I am here.",
        ),
        3: (
            "I am here with you. Let us take one slow breath together.",
            "It is okay to feel this way. I am right here with you.",
        ),
    },
    "distress": {
        1: ("Please tell a grown-up you trust.", "Talk to a grown-up you trust."),
        2: (
            "I want you to be safe. Please talk to a grown-up you trust.",
            "Please tell a grown-up you trust. They can help.",
        ),
        3: (
            "Thank you for telling me. Please talk to a grown-up you trust.",
            "I want you to be safe. Please talk to a grown-up you trust, they can help.",
        ),
    },
    "generic": {
        1: ("Let us keep going.", "Tell me more."),
        2: ("Let us keep going together.", "Tell me more about that."),
        3: ("Let us keep going, shall we?", "Tell me more about that, please."),
    },
}

MAX_NICKNAME_CHARS = 20
DEFAULT_NICKNAME = "friend"


def _nickname_slot(nickname: str | None) -> str:
    if nickname is None:
        return DEFAULT_NICKNAME
    cleaned = " ".join(nickname.split())[:MAX_NICKNAME_CHARS]
    return cleaned or DEFAULT_NICKNAME


def _level_key(level: int) -> int:
    if level <= 1:
        return 1
    if level == 2:
        return 2
    return 3


def pick_template(
    mode: Mode,
    level: int,
    event: Event,
    seed: int,
    nickname: str | None,
) -> str:
    """Choose a deterministic, safe fallback reply for the given combination."""

    chosen_event: Event = event if mode in EVENT_MODES.get(event, ()) else "generic"
    variants = TEMPLATES[chosen_event][_level_key(level)]
    chosen = variants[seed % len(variants)]
    return chosen.replace("{nickname}", _nickname_slot(nickname))
