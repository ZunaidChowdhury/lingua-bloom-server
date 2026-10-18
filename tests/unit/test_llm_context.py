from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.llm.context import MAX_TURNS, MAX_WINS, TRUNCATE_CHARS, build_context, context_json_size
from app.repositories.base import (
    AttemptRecord,
    MessageRecord,
    RecentWin,
    SessionRecord,
    TurnState,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
SESSION_ID = uuid.uuid4()


def _session(**overrides: object) -> SessionRecord:
    values: dict[str, object] = {
        "id": SESSION_ID,
        "token_hash": "hash",
        "nickname": "Mimi",
        "avatar": "sprout",
        "level": 2,
        "learning_streak": 1,
        "turns_since_checkin": 2,
        "turn_count": 5,
        "pending_item_id": None,
        "pending_attempts": 0,
        "last_feeling": "happy",
        "created_at": NOW,
        "last_active_at": NOW,
        "expires_at": NOW,
    }
    values.update(overrides)
    return SessionRecord(**values)  # type: ignore[arg-type]


def _message(message_id: int, role: str, content: str) -> MessageRecord:
    return MessageRecord(
        id=message_id,
        session_id=SESSION_ID,
        role=role,  # type: ignore[arg-type]
        content=content,
        mode=None,
        created_at=NOW,
    )


def _attempt(
    attempt_id: int, item_id: str, skill: str, result: str
) -> AttemptRecord:
    return AttemptRecord(
        id=attempt_id,
        session_id=SESSION_ID,
        item_id=item_id,
        level=2,
        skill_tag=skill,
        attempt_no=1,
        result=result,  # type: ignore[arg-type]
        counted=True,
        created_at=NOW,
    )


def _state(
    *,
    session: SessionRecord | None = None,
    messages: tuple[MessageRecord, ...] = (),
    attempts: tuple[AttemptRecord, ...] = (),
    skill_accuracy: dict[str, float] | None = None,
    wins: tuple[RecentWin, ...] = (),
) -> TurnState:
    return TurnState(
        session=session or _session(),
        messages=messages,
        recent_attempts=attempts,
        skill_accuracy=skill_accuracy or {},
        recent_wins=wins,
    )


def _full_session_state() -> TurnState:
    messages = tuple(
        _message(i, "child" if i % 2 == 0 else "bot", f"turn {i}")
        for i in range(1, 9)
    )
    attempts = (
        _attempt(1, "l2-animals-cat", "animals", "correct"),
        _attempt(2, "l2-animals-duck", "animals", "correct"),
        _attempt(3, "l2-colors-sky", "colors", "incorrect"),
    )
    wins = (
        RecentWin(item_id="l2-animals-cat", day_label="yesterday"),
        RecentWin(item_id="l2-animals-duck", day_label="today"),
    )
    return _state(
        session=_session(),
        messages=messages,
        attempts=attempts,
        skill_accuracy={"animals": 1.0, "colors": 0.0, "shapes": 0.75},
        wins=wins,
    )


def test_returns_all_required_keys() -> None:
    context = build_context(_full_session_state())
    assert set(context) == {
        "level",
        "nickname",
        "last_turns",
        "accuracy_last5",
        "strong_skills",
        "weak_skills",
        "last_event",
        "recent_wins",
        "latest_feeling",
    }


def test_values_come_from_stored_data() -> None:
    context = build_context(_full_session_state())
    assert context["level"] == 2
    assert context["nickname"] == "Mimi"
    assert context["latest_feeling"] == "happy"


def test_last_turns_maximum_six() -> None:
    context = build_context(_full_session_state())
    assert len(context["last_turns"]) == MAX_TURNS
    assert context["last_turns"][-1] == {"role": "child", "text": "turn 8"}
    assert context["last_turns"][0] == {"role": "bot", "text": "turn 3"}


def test_last_turns_truncated_to_120_chars() -> None:
    long_message = _message(1, "child", "x" * 300)
    context = build_context(_state(messages=(long_message,)))
    assert len(context["last_turns"][0]["text"]) == TRUNCATE_CHARS


def test_accuracy_last5_from_recent_attempts() -> None:
    context = build_context(_full_session_state())
    assert context["accuracy_last5"] == round(2 / 3, 2)


def test_accuracy_last5_empty_is_zero() -> None:
    context = build_context(_state())
    assert context["accuracy_last5"] == 0.0


def test_strong_and_weak_skill_buckets() -> None:
    context = build_context(_full_session_state())
    assert context["strong_skills"] == ["animals"]
    assert context["weak_skills"] == ["colors"]


def test_skills_are_sorted() -> None:
    state = _state(
        skill_accuracy={"a": 1.0, "b": 0.9, "c": 0.1, "d": 0.2},
    )
    context = build_context(state)
    assert context["strong_skills"] == ["a", "b"]
    assert context["weak_skills"] == ["c", "d"]


def test_last_event_from_latest_attempt() -> None:
    context = build_context(_full_session_state())
    assert context["last_event"] == {"type": "incorrect", "word": "sky"}


def test_last_event_none_without_attempts() -> None:
    context = build_context(_state())
    assert context["last_event"] is None


def test_recent_wins_only_correct_items_with_day_label() -> None:
    correct_ids = {
        attempt.item_id
        for attempt in _full_session_state().recent_attempts
        if attempt.result == "correct"
    }
    context = build_context(_full_session_state())
    assert len(context["recent_wins"]) == 2
    for win in context["recent_wins"]:
        assert win["word"] in {"cat", "duck"}
        assert win["when"] in {"today", "yesterday"}
    assert {w["word"] for w in context["recent_wins"]} == {
        item_id.rsplit("-", 1)[-1] for item_id in correct_ids
    }


def test_recent_wins_maximum_three() -> None:
    wins = tuple(
        RecentWin(item_id=f"l2-animals-pet{i}", day_label="today")
        for i in range(5)
    )
    context = build_context(_state(wins=wins))
    assert len(context["recent_wins"]) == MAX_WINS


def test_recent_wins_none_when_no_wins() -> None:
    context = build_context(_state())
    assert context["recent_wins"] == []


def test_word_derived_from_item_id() -> None:
    wins = (RecentWin(item_id="l1-colors-banana", day_label="today"),)
    context = build_context(_state(wins=wins))
    assert context["recent_wins"][0]["word"] == "banana"


def test_nickname_none_when_not_set() -> None:
    context = build_context(_state(session=_session(nickname=None)))
    assert context["nickname"] is None


def test_latest_feeling_none_when_not_set() -> None:
    context = build_context(_state(session=_session(last_feeling=None)))
    assert context["latest_feeling"] is None


def test_empty_session_context() -> None:
    context = build_context(_state())
    assert context == {
        "level": 2,
        "nickname": "Mimi",
        "last_turns": [],
        "accuracy_last5": 0.0,
        "strong_skills": [],
        "weak_skills": [],
        "last_event": None,
        "recent_wins": [],
        "latest_feeling": "happy",
    }


def test_full_session_json_at_most_1_5kb() -> None:
    context = build_context(_full_session_state())
    assert context_json_size(context) <= 1536
