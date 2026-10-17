from __future__ import annotations

import ast
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.domain.checking import AttemptResult, check_answer, normalize, words_match
from app.domain.curriculum.loader import load_level
from app.domain.curriculum.models import Item
from app.domain.errors import UnknownChoiceError

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "app" / "domain" / "curriculum" / "data"
CHECKING_FILE = ROOT / "app" / "domain" / "checking.py"
DOMAIN = ROOT / "app" / "domain"
BANNED = {"fastapi", "asyncpg", "groq", "starlette", "uvicorn"}


def _choice_item() -> Item:
    return Item.model_validate(
        {
            "id": "l1-color-banana",
            "level": 1,
            "skill": "colors",
            "type": "choice",
            "prompt": "What color is a banana?",
            "choices": [{"id": "a", "label": "Yellow"}, {"id": "b", "label": "Blue"}],
            "answer": {"choice_id": "a", "accepted_words": ["yellow"]},
            "hint": "Think.",
            "reveal": "Yellow.",
        }
    )


def _word_item() -> Item:
    item = _choice_item().model_dump()
    item["id"] = "l2-verbs-run"
    item["type"] = "word"
    item["prompt"] = "Type the word for moving fast."
    item["choices"] = []
    item["answer"] = {"choice_id": None, "accepted_words": ["run"]}
    return Item.model_validate(item)


def _fill_item() -> Item:
    item = _word_item().model_dump()
    item["id"] = "l2-sentences-fish-swim"
    item["type"] = "fill_blank"
    item["answer"] = {"choice_id": None, "accepted_words": ["swims", "swim"]}
    return Item.model_validate(item)


def _l3_items() -> dict[str, Item]:
    return {item.id: item for item in load_level(DATA / "l3.json", 3)}


def _samples() -> dict[str, dict[str, list[str]]]:
    return json.loads((DATA / "l3_rubric_samples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Hello!", "hello"),
        ("  the Cat  ", "cat"),
        ("A banana", "banana"),
        ("An apple", "apple"),
        ("THE DOG", "dog"),
        ("I can't!", "i cant"),
        ("🍌 banana", "banana"),
        ("good    morning", "good morning"),
        ("cats, dogs and birds", "cats dogs and birds"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("cats", "cat", True),
        ("cat", "cats", True),
        ("box", "boxes", True),
        ("run", "runs", True),
        ("book", "books", True),
        ("yellow", "yelow", True),
        ("apple", "aple", True),
        ("blue", "glue", True),
        ("happy", "happpy", True),
        ("the cat", "cat", True),
        ("Red ", "red", True),
        ("red", "rad", False),
        ("cat", "dog", False),
        ("milk", "milty", False),
        ("a", "b", False),
    ],
)
def test_words_match(left: str, right: str, expected: bool) -> None:
    assert words_match(left, right) is expected


def test_module_imports_only_domain_and_stdlib() -> None:
    tree = ast.parse(CHECKING_FILE.read_text(encoding="utf-8"))
    allowed = set(sys.stdlib_module_names) | {"app"}
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= allowed


def test_empty_answer_is_skipped() -> None:
    assert check_answer(_choice_item(), text="   ").reason == "skipped"


@pytest.mark.parametrize("phrase", ["idk", "I don't know", "DUNNO"])
def test_unsure_phrases_are_never_incorrect(phrase: str) -> None:
    result = check_answer(_word_item(), text=phrase)
    assert result.reason == "unsure"
    assert result.correct is False


@pytest.mark.parametrize("phrase", ["skip", "pass", "Skip"])
def test_skip_phrases_are_never_incorrect(phrase: str) -> None:
    assert check_answer(_word_item(), text=phrase).reason == "skipped"


def test_choice_by_id_correct() -> None:
    assert check_answer(_choice_item(), choice_id="a").correct is True


def test_choice_by_id_wrong() -> None:
    assert check_answer(_choice_item(), choice_id="b").correct is False


def test_choice_typed_label_correct() -> None:
    assert check_answer(_choice_item(), text="Yellow!").correct is True


def test_choice_typed_label_wrong() -> None:
    assert check_answer(_choice_item(), text="Blue").correct is False


def test_unknown_choice_id_raises_domain_error() -> None:
    with pytest.raises(UnknownChoiceError):
        check_answer(_choice_item(), choice_id="z")


@pytest.mark.parametrize(
    ("text", "expected"),
    [("run", True), ("Run!", True), ("running", False), ("jog", False)],
)
def test_word_matching(text: str, expected: bool) -> None:
    assert check_answer(_word_item(), text=text).correct is expected


@pytest.mark.parametrize(("text", "expected"), [("swims", True), ("swim", True), ("eats", False)])
def test_fill_blank_matching(text: str, expected: bool) -> None:
    assert check_answer(_fill_item(), text=text).correct is expected


@pytest.mark.parametrize("item_id", sorted(_samples()))
def test_sentence_pass_samples_are_correct(item_id: str) -> None:
    for text in _samples()[item_id]["pass"]:
        assert check_answer(_l3_items()[item_id], text=text).correct is True


@pytest.mark.parametrize("item_id", sorted(_samples()))
def test_sentence_fail_samples_are_incorrect(item_id: str) -> None:
    for text in _samples()[item_id]["fail"]:
        assert check_answer(_l3_items()[item_id], text=text).correct is False


def test_sentence_matched_but_not_correct() -> None:
    result = check_answer(_l3_items()["l3-build-happy"], text="Happy!")
    assert result.matched is True
    assert result.correct is False


def test_sentence_unmatched_when_no_keywords() -> None:
    result = check_answer(_l3_items()["l3-build-happy"], text="I am tired today now")
    assert result.matched is False
    assert result.correct is False


def test_attempt_result_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        AttemptResult(True, True, "correct").correct = False


def test_domain_has_no_framework_imports() -> None:
    for path in DOMAIN.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert not (roots & BANNED), f"{path.name} imports {roots & BANNED}"
