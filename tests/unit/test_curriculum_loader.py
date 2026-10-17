from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.curriculum.loader import CurriculumError, load_level
from app.domain.curriculum.models import Item, public_view


def _choice_item(index: int) -> dict[str, object]:
    return {
        "id": f"l1-item-{index}",
        "level": 1,
        "skill": "colors",
        "type": "choice",
        "prompt": f"What color is item {index}?",
        "emoji": "\U0001f34c",
        "choices": [
            {"id": "a", "label": "Yellow"},
            {"id": "b", "label": "Blue"},
            {"id": "c", "label": "Red"},
        ],
        "answer": {"choice_id": "a", "accepted_words": ["yellow"]},
        "hint": "Think of the sun.",
        "reveal": "It is yellow.",
    }


def _items(count: int = 20) -> list[dict[str, object]]:
    return [_choice_item(i) for i in range(count)]


def _write(tmp_path: Path, items: list[dict[str, object]]) -> Path:
    path = tmp_path / "l1.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def test_valid_level_loads(tmp_path: Path) -> None:
    items = load_level(_write(tmp_path, _items()), 1)
    assert len(items) == 20
    assert all(isinstance(item, Item) for item in items)


def test_too_few_items(tmp_path: Path) -> None:
    with pytest.raises(CurriculumError, match="at least 20"):
        load_level(_write(tmp_path, _items(19)), 1)


def test_duplicate_ids(tmp_path: Path) -> None:
    items = _items()
    items[1]["id"] = items[0]["id"]
    with pytest.raises(CurriculumError, match="duplicate id"):
        load_level(_write(tmp_path, items), 1)


def test_level_mismatch(tmp_path: Path) -> None:
    items = _items()
    items[0]["level"] = 2
    with pytest.raises(CurriculumError, match="does not match file level"):
        load_level(_write(tmp_path, items), 1)


def test_choice_needs_two_to_four(tmp_path: Path) -> None:
    items = _items()
    items[0]["choices"] = [{"id": "a", "label": "Yellow"}]
    with pytest.raises(CurriculumError, match="between 2 and 4"):
        load_level(_write(tmp_path, items), 1)


def test_choice_needs_exactly_one_correct(tmp_path: Path) -> None:
    items = _items()
    items[0]["answer"] = {"choice_id": "z"}
    with pytest.raises(CurriculumError, match="exactly one correct"):
        load_level(_write(tmp_path, items), 1)


def test_sentence_needs_rubric(tmp_path: Path) -> None:
    items = _items()
    items[0]["type"] = "sentence"
    items[0]["choices"] = []
    with pytest.raises(CurriculumError, match="rubric"):
        load_level(_write(tmp_path, items), 1)


def test_empty_hint(tmp_path: Path) -> None:
    items = _items()
    items[0]["hint"] = "   "
    with pytest.raises(CurriculumError, match="hint"):
        load_level(_write(tmp_path, items), 1)


def test_empty_reveal(tmp_path: Path) -> None:
    items = _items()
    items[0]["reveal"] = ""
    with pytest.raises(CurriculumError, match="reveal"):
        load_level(_write(tmp_path, items), 1)


def test_bad_type_is_rejected(tmp_path: Path) -> None:
    items = _items()
    items[0]["type"] = "essay"
    with pytest.raises(CurriculumError):
        load_level(_write(tmp_path, items), 1)


def test_error_names_file_and_item_id(tmp_path: Path) -> None:
    items = _items()
    items[0]["hint"] = ""
    with pytest.raises(CurriculumError) as info:
        load_level(_write(tmp_path, items), 1)
    assert "l1.json" in str(info.value)
    assert str(items[0]["id"]) in str(info.value)


def test_public_view_hides_server_fields(tmp_path: Path) -> None:
    item = load_level(_write(tmp_path, _items()), 1)[0]
    dumped = public_view(item).model_dump()
    assert "answer" not in dumped
    assert "accepted_words" not in dumped
    assert "rubric" not in dumped
    assert "reveal" not in dumped
