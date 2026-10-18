"""Build the compact context dictionary sent with every LLM call (FR-4.1, FR-4.4)."""

from __future__ import annotations

import json
from typing import TypedDict

from app.repositories.base import TurnState

MAX_TURNS = 6
TRUNCATE_CHARS = 120
MAX_WINS = 3
STRONG_ACCURACY = 0.8
WEAK_ACCURACY = 0.5


class TurnContext(TypedDict):
    """Compact, privacy-safe context for one LLM call."""

    level: int
    nickname: str | None
    last_turns: list[dict[str, str]]
    accuracy_last5: float
    strong_skills: list[str]
    weak_skills: list[str]
    last_event: dict[str, str] | None
    recent_wins: list[dict[str, str]]
    latest_feeling: str | None


def _word_from_item_id(item_id: str) -> str:
    """Extract the child-facing word from a curriculum item id like ``l1-colors-banana``."""

    return item_id.rsplit("-", 1)[-1]


def _accuracy_last5(state: TurnState) -> float:
    attempts = state.recent_attempts
    if not attempts:
        return 0.0
    correct = sum(1 for attempt in attempts if attempt.result == "correct")
    return correct / len(attempts)


def _skill_buckets(skill_accuracy: dict[str, float]) -> tuple[list[str], list[str]]:
    strong = sorted(
        (skill for skill, acc in skill_accuracy.items() if acc >= STRONG_ACCURACY),
        key=lambda skill: (-skill_accuracy[skill], skill),
    )
    weak = sorted(
        (skill for skill, acc in skill_accuracy.items() if acc < WEAK_ACCURACY),
        key=lambda skill: (skill_accuracy[skill], skill),
    )
    return strong, weak


def _last_event(state: TurnState) -> dict[str, str] | None:
    if not state.recent_attempts:
        return None
    latest = state.recent_attempts[-1]
    return {"type": latest.result, "word": _word_from_item_id(latest.item_id)}


def build_context(state: TurnState) -> TurnContext:
    """Return the compact context dictionary built only from stored data."""

    strong, weak = _skill_buckets(state.skill_accuracy)
    return TurnContext(
        level=state.session.level,
        nickname=state.session.nickname,
        last_turns=[
            {"role": message.role, "text": message.content[:TRUNCATE_CHARS]}
            for message in state.messages[-MAX_TURNS:]
        ],
        accuracy_last5=round(_accuracy_last5(state), 2),
        strong_skills=strong,
        weak_skills=weak,
        last_event=_last_event(state),
        recent_wins=[
            {"word": _word_from_item_id(win.item_id), "when": win.day_label}
            for win in state.recent_wins[:MAX_WINS]
        ],
        latest_feeling=state.session.last_feeling,
    )


def context_json_size(context: TurnContext) -> int:
    """Return the serialised size in bytes of one context dictionary."""

    return len(json.dumps(context, separators=(",", ":")).encode("utf-8"))
