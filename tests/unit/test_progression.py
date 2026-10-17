from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.checking import AttemptResult, Reason
from app.domain.progression import Action, CountedAttempt, apply_attempt, evaluate_progress

PROGRESSION_FILE = Path(__file__).resolve().parents[2] / "app" / "domain" / "progression.py"


def _attempts(spec: str, skills: list[str]) -> list[CountedAttempt]:
    return [
        CountedAttempt(skill=skills[index], correct=flag == "c")
        for index, flag in enumerate(spec)
    ]


def test_levelup_with_four_correct_and_three_skills() -> None:
    decision = evaluate_progress(
        _attempts("ccccw", ["colors", "animals", "food", "body", "colors"]), 1, Settings()
    )
    assert decision.leveled_up is True
    assert decision.next_level == 2
    assert decision.reset_window is True


def test_no_levelup_with_only_two_skills() -> None:
    decision = evaluate_progress(
        _attempts("ccccw", ["colors", "colors", "colors", "animals", "body"]), 1, Settings()
    )
    assert decision.leveled_up is False
    assert decision.next_level == 1


def test_no_levelup_with_three_correct() -> None:
    decision = evaluate_progress(
        _attempts("cccww", ["colors", "animals", "food", "body", "colors"]), 1, Settings()
    )
    assert decision.leveled_up is False
    assert decision.next_level == 1


def test_window_only_uses_last_five() -> None:
    attempts = _attempts("wccccw", ["body", "colors", "animals", "food", "body", "colors"])
    assert evaluate_progress(attempts, 1, Settings()).leveled_up is True
    attempts = _attempts("cccwww", ["colors", "animals", "food", "body", "colors", "animals"])
    assert evaluate_progress(attempts, 1, Settings()).leveled_up is False


def test_empty_window_never_levels_up() -> None:
    assert evaluate_progress([], 1, Settings()).leveled_up is False


def test_level_three_is_mastered_and_never_level_four() -> None:
    decision = evaluate_progress(
        _attempts("cccc", ["colors", "animals", "food", "body"]), 3, Settings()
    )
    assert decision.mastered is True
    assert decision.next_level == 3
    assert decision.leveled_up is False


def test_level_three_below_threshold_is_not_mastered() -> None:
    decision = evaluate_progress(
        _attempts("ccww", ["colors", "animals", "food", "body"]), 3, Settings()
    )
    assert decision.mastered is False
    assert decision.next_level == 3


def test_settings_overrides_change_behaviour() -> None:
    attempts = _attempts("cc", ["colors", "animals"])
    assert evaluate_progress(attempts, 1, Settings()).leveled_up is False
    loose = Settings(progress_required_correct=2, progress_min_distinct_skills=1)
    assert evaluate_progress(attempts, 1, loose).leveled_up is True


def test_no_demotion_path_exists() -> None:
    tree = ast.parse(PROGRESSION_FILE.read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    demotion = re.compile(r"demote|lower|downgrade|decrease", re.I)
    assert not any(demotion.search(name) for name in names)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            raise AssertionError("progression must never subtract from a level")


def _result(reason: Reason) -> AttemptResult:
    return AttemptResult(correct=reason == "correct", matched=False, reason=reason)


@pytest.mark.parametrize(
    ("pending", "reason", "action", "counted", "clears", "misses"),
    [
        (0, "correct", "advance", True, True, 0),
        (1, "correct", "advance", False, True, 1),
        (0, "incorrect", "retry", True, False, 1),
        (1, "incorrect", "hint", False, False, 2),
        (2, "incorrect", "reveal", False, True, 3),
        (0, "unsure", "retry", False, False, 0),
        (0, "skipped", "retry", False, False, 0),
    ],
)
def test_attempt_transitions(
    pending: int, reason: Reason, action: Action, counted: bool, clears: bool, misses: int
) -> None:
    decision = apply_attempt(pending, _result(reason), Settings())
    assert decision.action == action
    assert decision.counted is counted
    assert decision.clears_pending is clears
    assert decision.miss_count == misses


def test_reveal_is_the_stop_after_three_misses() -> None:
    decision = apply_attempt(3, _result("incorrect"), Settings())
    assert decision.action == "reveal"
    assert decision.clears_pending is True


def test_unsure_and_skipped_never_count() -> None:
    uncounted: tuple[Reason, ...] = ("unsure", "skipped")
    for reason in uncounted:
        decision = apply_attempt(0, _result(reason), Settings())
        assert decision.counted is False
        assert decision.miss_count == 0


def test_settings_thresholds_are_respected() -> None:
    tight = Settings(hint_after_misses=1, reveal_after_misses=2)
    assert apply_attempt(0, _result("incorrect"), tight).action == "hint"
    assert apply_attempt(1, _result("incorrect"), tight).action == "reveal"
