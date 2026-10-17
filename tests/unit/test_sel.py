from __future__ import annotations

import pytest

from app.core.config import Settings
from app.domain.sel import (
    BANNED_FEEDBACK_WORDS,
    EFFORT_PRAISE,
    FEELINGS,
    FEELINGS_BY_ID,
    TRY_AGAIN_LINE,
    checkin_due,
    feeling_checkin,
    support_steps,
)


def test_checkin_due_on_cadence() -> None:
    assert checkin_due(8, has_pending_item=False, mode="conversation", settings=Settings()) is True


def test_checkin_not_due_before_cadence() -> None:
    assert checkin_due(7, has_pending_item=False, mode="conversation", settings=Settings()) is False


def test_checkin_not_due_while_item_pending() -> None:
    assert checkin_due(8, has_pending_item=True, mode="learning", settings=Settings()) is False


def test_checkin_not_due_in_support() -> None:
    assert checkin_due(8, has_pending_item=False, mode="support", settings=Settings()) is False


def test_checkin_follows_custom_cadence() -> None:
    settings = Settings(checkin_every_n_turns=3)
    assert checkin_due(3, has_pending_item=False, mode="conversation", settings=settings) is True


def test_feelings_catalogue_ids() -> None:
    assert [feeling.id for feeling in FEELINGS] == ["happy", "excited", "sleepy", "worried", "sad"]


@pytest.mark.parametrize(
    ("feeling_id", "mood"),
    [
        ("happy", "positive"),
        ("excited", "positive"),
        ("sleepy", "neutral"),
        ("worried", "low"),
        ("sad", "low"),
    ],
)
def test_feeling_mood_mapping(feeling_id: str, mood: str) -> None:
    assert FEELINGS_BY_ID[feeling_id].mood == mood


@pytest.mark.parametrize("feeling_id", ["worried", "sad"])
def test_low_feelings_route_to_support(feeling_id: str) -> None:
    assert FEELINGS_BY_ID[feeling_id].routes_to_support is True


@pytest.mark.parametrize("feeling_id", ["happy", "excited", "sleepy"])
def test_other_feelings_do_not_route_to_support(feeling_id: str) -> None:
    assert FEELINGS_BY_ID[feeling_id].routes_to_support is False


def test_every_feeling_has_an_emoji() -> None:
    assert all(feeling.emoji for feeling in FEELINGS)


def test_feeling_checkin_activity_shape() -> None:
    activity = feeling_checkin()
    assert activity.type == "feeling_checkin"
    assert [choice.id for choice in activity.choices] == [
        "happy",
        "excited",
        "sleepy",
        "worried",
        "sad",
    ]
    assert all(choice.emoji and choice.label for choice in activity.choices)


@pytest.mark.parametrize("level", [1, 2, 3, 9])
def test_support_steps_never_include_a_quiz(level: int) -> None:
    playbook = support_steps(level)
    text = " ".join((playbook.acknowledge, playbook.gentle_step, *playbook.choices))
    assert "quiz" not in text.lower()


def test_support_steps_have_three_stages() -> None:
    playbook = support_steps(1)
    assert playbook.acknowledge
    assert playbook.gentle_step
    assert playbook.choices == ("rest", "chat", "easier_game")


def test_support_steps_are_level_appropriate() -> None:
    short = support_steps(1)
    long = support_steps(3)
    assert len(short.gentle_step.split()) <= len(long.gentle_step.split())


def test_banned_feedback_words() -> None:
    assert {"wrong", "bad", "fail", "stupid"} == BANNED_FEEDBACK_WORDS


@pytest.mark.parametrize("banned", sorted(BANNED_FEEDBACK_WORDS))
def test_feedback_vocabulary_has_no_banned_words(banned: str) -> None:
    for line in (*EFFORT_PRAISE, TRY_AGAIN_LINE):
        assert banned not in line.lower()
