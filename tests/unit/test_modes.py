from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.core.config import Settings
from app.domain.modes import ALL_MODES, decide_mode, detect_signals, validate_suggestion


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("i sad", "support"),
        ("im sad", "support"),
        ("i am sad", "support"),
        ("i dont want to", "support"),
        ("i cant do it", "support"),
        ("im scared", "support"),
        ("i feel lonely", "support"),
        ("tell me a story", "wants_story"),
        ("i want a story", "wants_story"),
        ("read me a tale", "wants_story"),
        ("lets play", "wants_play"),
        ("can we play a game", "wants_play"),
        ("i want to pretend", "wants_play"),
        ("teach me", "wants_learning"),
        ("quiz me", "wants_learning"),
        ("i want to learn", "wants_learning"),
        ("practice with me", "wants_learning"),
        ("boring", "low_effort"),
        ("no", "low_effort"),
        ("idk", "low_effort"),
        ("idk", "unsure"),
        ("dunno", "unsure"),
        ("i dont know", "unsure"),
    ],
)
def test_signal_flags_true(text: str, flag: str) -> None:
    assert getattr(detect_signals(text), flag) is True


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("red", "support"),
        ("i like red", "support"),
        ("sadly funny cat", "support"),
        ("sadly funny cat", "severe_distress"),
        ("the cat sat", "wants_story"),
        ("playful puppy", "wants_play"),
        ("learning is fun", "wants_learning"),
        ("nobody here", "low_effort"),
        ("notebook", "wants_learning"),
    ],
)
def test_signal_flags_false(text: str, flag: str) -> None:
    assert getattr(detect_signals(text), flag) is False


@pytest.mark.parametrize(
    "text",
    ["i want to die", "kill myself", "i want to hurt myself", "end my life"],
)
def test_severe_distress_is_detected(text: str) -> None:
    assert detect_signals(text).severe_distress is True


def test_neutral_message_has_no_signals() -> None:
    signals = detect_signals("i like the blue ball")
    assert not any(vars(signals).values())


def test_signals_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        detect_signals("hi").support = True  # type: ignore[misc]


def test_row1_support_wins_over_everything() -> None:
    decision = decide_mode(
        detect_signals("i sad"),
        has_pending_attempt=True,
        learning_streak=5,
        settings=Settings(),
    )
    assert decision.mode == "support"
    assert decision.allows_new_item is False


def test_row2_pending_attempt_is_learning() -> None:
    decision = decide_mode(
        detect_signals("cat"),
        has_pending_attempt=True,
        learning_streak=0,
        settings=Settings(),
    )
    assert decision.mode == "learning"
    assert decision.allows_new_item is True


def test_row3_story_request_is_engagement() -> None:
    decision = decide_mode(
        detect_signals("tell me a story"),
        has_pending_attempt=False,
        learning_streak=0,
        settings=Settings(),
    )
    assert decision.mode == "engagement"


def test_row3_play_request_is_engagement() -> None:
    decision = decide_mode(
        detect_signals("lets play"),
        has_pending_attempt=False,
        learning_streak=0,
        settings=Settings(),
    )
    assert decision.mode == "engagement"


def test_row4_learning_request_overrides_pacing() -> None:
    decision = decide_mode(
        detect_signals("quiz me"),
        has_pending_attempt=False,
        learning_streak=9,
        settings=Settings(),
    )
    assert decision.mode == "learning"
    assert decision.allows_new_item is True


def test_row5_pacing_removes_learning_at_streak() -> None:
    decision = decide_mode(
        detect_signals("hello"),
        has_pending_attempt=False,
        learning_streak=3,
        settings=Settings(),
    )
    assert decision.mode == "auto"
    assert "learning" not in decision.allowed_modes
    assert decision.allows_new_item is False


def test_row6_auto_allows_learning_below_streak() -> None:
    decision = decide_mode(
        detect_signals("hello"),
        has_pending_attempt=False,
        learning_streak=0,
        settings=Settings(),
    )
    assert decision.mode == "auto"
    assert set(decision.allowed_modes) == set(ALL_MODES)
    assert decision.allows_new_item is True


def test_row7_invalid_suggestion_defaults_to_conversation() -> None:
    assert validate_suggestion("singing", 0.9, ALL_MODES) == "conversation"
    assert validate_suggestion(None, 1.0, ALL_MODES) == "conversation"


def test_validate_suggestion_accepts_allowed_high_confidence() -> None:
    assert validate_suggestion("engagement", 0.9, ("engagement", "conversation")) == "engagement"


def test_validate_suggestion_rejects_low_confidence() -> None:
    assert validate_suggestion("engagement", 0.49, ALL_MODES) == "conversation"


def test_validate_suggestion_rejects_disallowed_mode() -> None:
    assert validate_suggestion("learning", 0.9, ("conversation",)) == "conversation"


def test_four_modes_are_each_reachable() -> None:
    settings = Settings()
    reachable = {
        decide_mode(detect_signals("i sad"), False, 0, settings).mode,
        decide_mode(detect_signals("cat"), True, 0, settings).mode,
        decide_mode(detect_signals("lets play"), False, 0, settings).mode,
        validate_suggestion(None, 0.0, ALL_MODES),
    }
    assert reachable == {"support", "learning", "engagement", "conversation"}


def test_pacing_simulation_never_four_learning_in_a_row() -> None:
    settings = Settings()
    streak = 0
    run = 0
    longest = 0
    for _ in range(20):
        decision = decide_mode(
            detect_signals("hello"),
            has_pending_attempt=False,
            learning_streak=streak,
            settings=settings,
        )
        if decision.mode == "auto":
            chosen = validate_suggestion("learning", 0.9, decision.allowed_modes)
        else:
            chosen = decision.mode
        if chosen == "learning":
            run += 1
            streak += 1
        else:
            run = 0
            streak = 0
        longest = max(longest, run)
    assert longest <= 3
