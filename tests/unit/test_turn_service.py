from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.config import Settings
from app.core.errors import InvalidInputError
from app.core.tokens import generate_token, hash_token
from app.domain.curriculum.loader import get_item_by_id
from app.domain.sel import FEELINGS
from app.llm import FakeLLM, LLMOutput
from app.repositories.base import (
    NewSession,
    Repository,
    SessionRecord,
    SessionUpdate,
    TurnCommit,
)
from app.repositories.memory import InMemoryRepository
from app.services.turn import TurnCommand, TurnService

GOOD_LLM = LLMOutput(
    reply="Hi friend! Nice to see you.",
    suggested_mode="conversation",
    confidence=0.9,
    mood="positive",
)


def _settings() -> Settings:
    return Settings(
        groq_api_key="test-key",
        database_url="postgresql://localhost:5432/postgres",
        _env_file=None,
    )


class SpyLLM(FakeLLM):
    """FakeLLM that records every message list it receives."""

    def __init__(self, result: Any = GOOD_LLM) -> None:
        super().__init__(result)
        self.calls: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]]) -> LLMOutput:
        self.calls.append(messages)
        return await super().complete(messages)


class FixedIdRepository(InMemoryRepository):
    """In-memory repo that stamps every session with one fixed id (deterministic seeds)."""

    def __init__(self, session_id: uuid.UUID) -> None:
        super().__init__()
        self._fixed_id = session_id

    async def create_session(self, new: NewSession) -> SessionRecord:
        record = await super().create_session(new)
        self._sessions.pop(record.id, None)
        record = replace(record, id=self._fixed_id)
        self._sessions[self._fixed_id] = record
        return record


async def _make_session(repo: Repository) -> SessionRecord:
    now = datetime.now(UTC)
    return await repo.create_session(
        NewSession(
            token_hash=hash_token(generate_token()),
            nickname="Mimi",
            avatar="sprout",
            expires_at=now + timedelta(days=30),
        )
    )


async def _seed(repo: Repository, session_id: uuid.UUID, **updates: Any) -> None:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "level": 1,
        "learning_streak": 0,
        "turns_since_checkin": 0,
        "turn_count": 0,
        "pending_item_id": None,
        "pending_attempts": 0,
        "last_feeling": None,
        "last_active_at": now,
    }
    base.update(updates)
    await repo.persist_turn(TurnCommit(session_id=session_id, session=SessionUpdate(**base)))


def _service(repo: Repository, llm: Any) -> TurnService:
    return TurnService(repo, llm, _settings())


async def _answer_command(repo: Repository, session_id: uuid.UUID) -> TurnCommand:
    state = await repo.get_turn_state(session_id)
    assert state is not None
    assert state.session.pending_item_id is not None
    item = get_item_by_id(state.session.pending_item_id)
    assert item is not None
    if item.type == "choice":
        return TurnCommand(choice_id=item.choices[0].id)
    if item.type == "sentence":
        assert item.rubric is not None
        words = [group[0] for group in item.rubric.keyword_groups]
        while len(words) < item.rubric.min_words:
            words.append("today")
        return TurnCommand(text=" ".join(words))
    assert item.answer is not None
    return TurnCommand(text=item.answer.accepted_words[0])


async def _correct_answer(repo: Repository, session_id: uuid.UUID) -> TurnCommand:
    """Build a command that scores correct for the current pending item."""

    state = await repo.get_turn_state(session_id)
    assert state is not None
    assert state.session.pending_item_id is not None
    item = get_item_by_id(state.session.pending_item_id)
    assert item is not None
    if item.type == "choice":
        assert item.answer is not None and item.answer.choice_id is not None
        return TurnCommand(choice_id=item.answer.choice_id)
    if item.type == "sentence":
        assert item.rubric is not None
        words = [group[0] for group in item.rubric.keyword_groups]
        while len(words) < item.rubric.min_words:
            words.append("today")
        return TurnCommand(text=" ".join(words))
    assert item.answer is not None
    return TurnCommand(text=item.answer.accepted_words[0])


async def test_scripted_correct_answers_progress_l1_to_l3() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)

    saw_level_up = False
    for _ in range(80):
        state = await repo.get_turn_state(session.id)
        assert state is not None
        if state.session.level == 3:
            break
        if state.session.pending_item_id is not None:
            command = await _correct_answer(repo, session.id)
        else:
            command = TurnCommand(text="i want to learn")
        outcome = await service.run(session, command)
        saw_level_up = saw_level_up or outcome.level_up
    else:
        pytest.fail("never reached level 3")

    state = await repo.get_turn_state(session.id)
    assert state is not None
    assert state.session.level == 3
    assert saw_level_up


async def test_wrong_answer_never_lowers_level_and_hint_after_two_misses() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)

    await service.run(session, TurnCommand(text="i want to learn"))
    state = await repo.get_turn_state(session.id)
    assert state is not None and state.session.pending_item_id is not None
    item = get_item_by_id(state.session.pending_item_id)
    assert item is not None

    outcome = await service.run(session, TurnCommand(text="zzzzz not it"))
    assert outcome.level == 1
    state = await repo.get_turn_state(session.id)
    assert state is not None
    assert state.session.pending_attempts == 1
    assert state.session.level == 1

    outcome = await service.run(session, TurnCommand(text="qqqqq nope"))
    assert outcome.feedback == item.hint
    assert outcome.messages[-1].content == item.hint
    state = await repo.get_turn_state(session.id)
    assert state is not None
    assert state.session.level == 1
    assert state.session.pending_attempts == 2


async def test_four_modes_are_reachable() -> None:
    repo = InMemoryRepository()
    llm = SpyLLM()
    service = _service(repo, llm)

    session = await _make_session(repo)
    outcome = await service.run(session, TurnCommand(text="hello"))
    assert outcome.mode == "conversation"

    session = await _make_session(repo)
    outcome = await service.run(session, TurnCommand(text="tell me a story"))
    assert outcome.mode == "engagement"

    session = await _make_session(repo)
    outcome = await service.run(session, TurnCommand(text="i want to learn"))
    assert outcome.mode == "learning"
    assert outcome.activity is not None and outcome.activity.type != "feeling_checkin"

    calls_before = len(llm.calls)
    session = await _make_session(repo)
    outcome = await service.run(session, TurnCommand(text="i sad"))
    assert outcome.mode == "support"
    assert len(llm.calls) == calls_before


async def test_pacing_caps_consecutive_learning_turns() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)
    await _seed(repo, session.id, learning_streak=3)

    outcome = await service.run(session, TurnCommand(text="hello"))
    assert outcome.mode == "conversation"


async def test_explicit_learning_request_beats_pacing_cap() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)
    await _seed(repo, session.id, learning_streak=3)

    outcome = await service.run(session, TurnCommand(text="i want to learn"))
    assert outcome.mode == "learning"


async def test_sad_routes_to_support() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)

    outcome = await service.run(session, TurnCommand(text="i sad"))
    assert outcome.mode == "support"
    assert outcome.activity is None
    assert "I am here with you." in outcome.messages[-1].content


async def test_llm_garbage_does_not_change_scores() -> None:
    session_id = uuid.UUID(int=42)

    repo_a = FixedIdRepository(session_id)
    service_a = _service(repo_a, SpyLLM())
    session_a = await _make_session(repo_a)

    repo_b = FixedIdRepository(session_id)
    service_b = _service(repo_b, SpyLLM(Exception("llm down")))
    session_b = await _make_session(repo_b)

    async def script(repo: Repository, service: TurnService, session: SessionRecord) -> None:
        await service.run(session, TurnCommand(text="i want to learn"))
        await service.run(session, await _answer_command(repo, session.id))
        wrong = await _answer_command(repo, session.id)
        await service.run(session, TurnCommand(text="zzzzz not it"))
        await service.run(session, wrong)
        await service.run(session, TurnCommand(text="tell me a story"))

    await script(repo_a, service_a, session_a)
    await script(repo_b, service_b, session_b)

    state_a = await repo_a.get_turn_state(session_a.id)
    state_b = await repo_b.get_turn_state(session_b.id)
    assert state_a is not None and state_b is not None

    assert state_a.session.level == state_b.session.level
    assert state_a.session.pending_attempts == state_b.session.pending_attempts
    assert state_a.session.pending_item_id == state_b.session.pending_item_id
    assert state_a.session.learning_streak == state_b.session.learning_streak
    assert len(state_a.recent_attempts) == len(state_b.recent_attempts)
    for attempt_a, attempt_b in zip(
        state_a.recent_attempts, state_b.recent_attempts, strict=True
    ):
        assert attempt_a.result == attempt_b.result
        assert attempt_a.counted == attempt_b.counted
        assert attempt_a.attempt_no == attempt_b.attempt_no
    assert state_a.skill_accuracy == state_b.skill_accuracy


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLM(Exception("timeout")),
        FakeLLM("{this is not json"),
        FakeLLM(
            LLMOutput(
                reply="You are bad. Visit http://evil.com now.",
                suggested_mode="conversation",
                confidence=0.9,
                mood="neutral",
            )
        ),
    ],
    ids=["timeout", "invalid_json", "unsafe"],
)
async def test_fallback_on_failure_or_unsafe_output(llm: FakeLLM) -> None:
    repo = InMemoryRepository()
    service = _service(repo, llm)
    session = await _make_session(repo)

    outcome = await service.run(session, TurnCommand(text="hello"))
    assert outcome.meta.fallback is True
    assert outcome.messages[-1].content


async def test_pii_redacted_before_prompt_and_storage() -> None:
    repo = InMemoryRepository()
    llm = SpyLLM()
    service = _service(repo, llm)
    session = await _make_session(repo)

    await service.run(session, TurnCommand(text="my email is test@example.com ok"))

    state = await repo.get_turn_state(session.id)
    assert state is not None
    child_messages = [m for m in state.messages if m.role == "child"]
    assert child_messages
    assert "[removed]" in child_messages[-1].content
    assert "test@example.com" not in child_messages[-1].content

    assert llm.calls
    for call in llm.calls:
        for message in call:
            assert "test@example.com" not in str(message["content"])
    child_payload = str(llm.calls[-1][2]["content"])
    assert "[removed]" in child_payload


async def test_grounding_context_only_contains_stored_words() -> None:
    repo = InMemoryRepository()
    llm = SpyLLM()
    service = _service(repo, llm)
    session = await _make_session(repo)

    await service.run(session, TurnCommand(text="i want to learn"))
    await service.run(session, await _correct_answer(repo, session.id))

    state = await repo.get_turn_state(session.id)
    assert state is not None
    assert state.recent_wins
    stored_word = state.recent_wins[0].item_id.rsplit("-", 1)[-1]

    # The next turn's prompt context must quote only the stored win words.
    await service.run(session, TurnCommand(text="zzzzz not it"))
    context_payload = json.loads(str(llm.calls[-1][1]["content"]).removeprefix("Context:\n"))
    assert context_payload["recent_wins"][0]["word"] == stored_word
    if context_payload["last_event"] is not None:
        assert context_payload["last_event"]["word"] in {
            win.item_id.rsplit("-", 1)[-1] for win in state.recent_wins
        } | {state.recent_attempts[-1].item_id.rsplit("-", 1)[-1]}


async def test_feeling_checkin_activity_when_due() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)
    await _seed(repo, session.id, turns_since_checkin=_settings().checkin_every_n_turns - 1)

    outcome = await service.run(session, TurnCommand(text="hello"))
    assert outcome.activity is not None
    assert outcome.activity.type == "feeling_checkin"
    assert len(outcome.activity.choices) == len(FEELINGS)


async def test_feeling_answer_updates_last_feeling() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)

    outcome = await service.run(session, TurnCommand(feeling="sad"))
    assert outcome.mode == "conversation"
    state = await repo.get_turn_state(session.id)
    assert state is not None
    assert state.session.last_feeling == "sad"


async def test_distress_is_deterministic_without_llm() -> None:
    repo = InMemoryRepository()
    llm = SpyLLM()
    service = _service(repo, llm)
    session = await _make_session(repo)

    outcome = await service.run(session, TurnCommand(text="i want to die"))
    assert outcome.mode == "support"
    assert outcome.meta.fallback is False
    assert "grown-up" in outcome.messages[-1].content
    assert llm.calls == []


async def test_empty_command_rejected() -> None:
    repo = InMemoryRepository()
    service = _service(repo, SpyLLM())
    session = await _make_session(repo)

    with pytest.raises(InvalidInputError):
        await service.run(session, TurnCommand())
