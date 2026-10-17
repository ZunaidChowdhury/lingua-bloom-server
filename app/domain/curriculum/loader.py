"""Load and validate the versioned curriculum JSON (FR-1.2, FR-1.7)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from app.domain.curriculum.models import Item

MIN_ITEMS_PER_LEVEL = 20
MIN_CHOICES = 2
MAX_CHOICES = 4
LEVEL_FILES: dict[int, str] = {1: "l1.json", 2: "l2.json", 3: "l3.json"}


class CurriculumError(ValueError):
    """Raised when a curriculum file breaks a validation rule."""


def _fail(path: Path, message: str, item_id: str | None = None) -> CurriculumError:
    where = path.name if item_id is None else f"{path.name}: item {item_id}"
    return CurriculumError(f"{where}: {message}")


def _parse_item(path: Path, raw: object) -> Item:
    if not isinstance(raw, dict):
        raise _fail(path, "each item must be a JSON object")
    item_id = raw.get("id")
    label = item_id if isinstance(item_id, str) else None
    try:
        return Item.model_validate(raw)
    except ValidationError as exc:
        raise _fail(path, str(exc.errors()[0]["msg"]), label) from exc


def _validate_item(path: Path, item: Item, expected_level: int) -> None:
    if item.level != expected_level:
        raise _fail(path, f"level {item.level} does not match file level {expected_level}", item.id)
    if not item.hint.strip():
        raise _fail(path, "hint must not be empty", item.id)
    if not item.reveal.strip():
        raise _fail(path, "reveal must not be empty", item.id)
    if item.type == "choice":
        if not MIN_CHOICES <= len(item.choices) <= MAX_CHOICES:
            raise _fail(path, "choice items need between 2 and 4 choices", item.id)
        if item.answer is None or item.answer.choice_id is None:
            raise _fail(path, "choice items need a correct choice_id", item.id)
        correct = [choice for choice in item.choices if choice.id == item.answer.choice_id]
        if len(correct) != 1:
            raise _fail(path, "choice items need exactly one correct id", item.id)
    if item.type == "sentence" and item.rubric is None:
        raise _fail(path, "sentence items need a rubric", item.id)


def load_level(path: Path, expected_level: int) -> list[Item]:
    """Read, parse, and validate one level file, or raise CurriculumError."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _fail(path, "file not found") from exc
    except json.JSONDecodeError as exc:
        raise _fail(path, "invalid JSON") from exc

    if not isinstance(raw, list):
        raise _fail(path, "file must contain a JSON array of items")

    items: list[Item] = []
    seen: set[str] = set()
    for entry in raw:
        item = _parse_item(path, entry)
        if item.id in seen:
            raise _fail(path, f"duplicate id {item.id}", item.id)
        seen.add(item.id)
        _validate_item(path, item, expected_level)
        items.append(item)

    if len(items) < MIN_ITEMS_PER_LEVEL:
        raise _fail(path, f"needs at least {MIN_ITEMS_PER_LEVEL} items, found {len(items)}")

    return items


def load_curriculum(data_dir: Path | None = None) -> dict[int, list[Item]]:
    """Load all three levels. Intended to be called once at application startup."""

    base = data_dir or (Path(__file__).parent / "data")
    return {level: load_level(base / name, level) for level, name in LEVEL_FILES.items()}
