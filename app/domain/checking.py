"""Deterministic answer checking for every curriculum item type (FR-1.3)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.domain.curriculum.models import Item, Rubric
from app.domain.errors import UnknownChoiceError

Reason = Literal["correct", "incorrect", "unsure", "skipped"]

LEADING_ARTICLES = frozenset({"a", "an", "the"})
MIN_FUZZY_LENGTH = 4
UNSURE_PHRASES = frozenset({"idk", "i dont know", "dunno"})
SKIP_PHRASES = frozenset({"skip", "pass"})
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+", re.UNICODE)


@dataclass(frozen=True)
class AttemptResult:
    """Outcome of one child attempt. `unsure` and `skipped` are never penalised."""

    correct: bool
    matched: bool
    reason: Reason


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and emoji, collapse whitespace, drop a leading article."""

    without_symbols = _PUNCTUATION.sub("", text.lower())
    words = _WHITESPACE.sub(" ", without_symbols).strip().split()
    if words and words[0] in LEADING_ARTICLES:
        words = words[1:]
    return " ".join(words)


def _simple_plural(left: str, right: str) -> bool:
    for longer, shorter in ((left, right), (right, left)):
        if longer in (f"{shorter}s", f"{shorter}es"):
            return True
    return False


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 1:
        return 2
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def words_match(left: str, right: str) -> bool:
    """Return True when two answers are equal, simple plurals, or one typo apart."""

    a = normalize(left)
    b = normalize(right)
    if a == b:
        return True
    if _simple_plural(a, b):
        return True
    return min(len(a), len(b)) >= MIN_FUZZY_LENGTH and _edit_distance(a, b) <= 1


def _matches_accepted(item: Item, typed: str) -> bool:
    if item.answer is None:
        return False
    return any(words_match(typed, word) for word in item.answer.accepted_words)


def _group_matches(group: list[str], normalised_text: str) -> bool:
    words = normalised_text.split()
    for keyword in group:
        key = normalize(keyword)
        if key and (key == normalised_text or any(words_match(word, key) for word in words)):
            return True
    return False


def _check_choice(item: Item, choice_id: str | None, typed: str) -> AttemptResult:
    if choice_id is not None:
        known_ids = {choice.id for choice in item.choices}
        if choice_id not in known_ids:
            raise UnknownChoiceError(item.id)
        correct_id = item.answer.choice_id if item.answer else None
        if choice_id == correct_id:
            return AttemptResult(True, True, "correct")
        return AttemptResult(False, False, "incorrect")
    if _matches_accepted(item, typed):
        return AttemptResult(True, True, "correct")
    return AttemptResult(False, False, "incorrect")


def _check_accepted(item: Item, typed: str) -> AttemptResult:
    if _matches_accepted(item, typed):
        return AttemptResult(True, True, "correct")
    return AttemptResult(False, False, "incorrect")


def _check_sentence(item: Item, normalised: str) -> AttemptResult:
    rubric: Rubric | None = item.rubric
    if rubric is None:
        return AttemptResult(False, False, "incorrect")
    words = normalised.split()
    all_groups = bool(rubric.keyword_groups) and all(
        _group_matches(group, normalised) for group in rubric.keyword_groups
    )
    any_group = any(_group_matches(group, normalised) for group in rubric.keyword_groups)
    count_ok = rubric.min_words <= len(words) <= rubric.max_words
    pattern_ok = True
    if rubric.pattern:
        pattern_ok = re.search(rubric.pattern, normalised) is not None
    correct = all_groups and count_ok and pattern_ok
    return AttemptResult(correct, any_group, "correct" if correct else "incorrect")


def check_answer(
    item: Item,
    choice_id: str | None = None,
    text: str | None = None,
) -> AttemptResult:
    """Score one attempt deterministically. The LLM is never involved."""

    typed = (text or "").strip()
    if not typed and choice_id is None:
        return AttemptResult(False, False, "skipped")

    normalised = normalize(typed) if typed else ""
    if normalised in UNSURE_PHRASES:
        return AttemptResult(False, False, "unsure")
    if normalised in SKIP_PHRASES:
        return AttemptResult(False, False, "skipped")

    if item.type == "choice":
        return _check_choice(item, choice_id, typed)
    if item.type in ("word", "fill_blank"):
        return _check_accepted(item, typed)
    if item.type == "sentence":
        return _check_sentence(item, normalised)
    return AttemptResult(False, False, "incorrect")
