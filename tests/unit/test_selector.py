from __future__ import annotations

from app.domain.curriculum.models import Item
from app.domain.curriculum.selector import ItemSelector, shuffled_choices


def _item(item_id: str, level: int, skill: str, choice_count: int = 3) -> Item:
    return Item.model_validate(
        {
            "id": item_id,
            "level": level,
            "skill": skill,
            "type": "choice",
            "prompt": f"Pick for {item_id}?",
            "choices": [{"id": chr(97 + i), "label": f"Option {i}"} for i in range(choice_count)],
            "answer": {"choice_id": "a", "accepted_words": []},
            "hint": "Think.",
            "reveal": "Done.",
        }
    )


def test_returns_requested_level() -> None:
    bank = {1: [_item("a", 1, "colors")], 2: [_item("b", 2, "verbs")]}
    assert ItemSelector(bank).select_next(2, {}, [], 1).id == "b"


def test_excludes_recently_seen() -> None:
    bank = {1: [_item("a", 1, "colors"), _item("b", 1, "colors"), _item("c", 1, "colors")]}
    chosen = ItemSelector(bank).select_next(1, {}, ["b", "c"], 7)
    assert chosen.id == "a"


def test_exhaustion_reuses_oldest_seen() -> None:
    bank = {1: [_item("a", 1, "colors"), _item("b", 1, "colors")]}
    chosen = ItemSelector(bank).select_next(1, {}, ["a", "b"], 7)
    assert chosen.id == "a"


def test_same_seed_same_item() -> None:
    bank = {1: [_item("a", 1, "colors"), _item("b", 1, "verbs")]}
    selector = ItemSelector(bank)
    assert selector.select_next(1, {}, [], 99).id == selector.select_next(1, {}, [], 99).id


def test_weak_skill_weighted_more() -> None:
    bank = {1: [_item("weak", 1, "verbs"), _item("strong", 1, "colors")]}
    selector = ItemSelector(bank)
    stats = {"verbs": 0.0, "colors": 1.0}
    weak_hits = sum(selector.select_next(1, stats, [], seed).id == "weak" for seed in range(300))
    assert weak_hits > 150


def test_shuffled_choices_stable_per_session_item() -> None:
    item = _item("a", 1, "colors", choice_count=4)
    first = shuffled_choices(item, "session-1")
    second = shuffled_choices(item, "session-1")
    assert [choice.id for choice in first] == [choice.id for choice in second]


def test_shuffled_choices_is_a_permutation() -> None:
    item = _item("a", 1, "colors", choice_count=4)
    order = [choice.id for choice in shuffled_choices(item, "session-2")]
    assert sorted(order) == ["a", "b", "c", "d"]
