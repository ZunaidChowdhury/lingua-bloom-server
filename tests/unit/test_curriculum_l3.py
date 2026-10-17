from __future__ import annotations

import json
from pathlib import Path

from app.domain.curriculum.loader import load_level

DATA = Path(__file__).resolve().parents[2] / "app" / "domain" / "curriculum" / "data"


def _l3_items():
    return load_level(DATA / "l3.json", 3)


def test_l3_type_counts() -> None:
    items = _l3_items()
    assert len(items) >= 22
    assert len([item for item in items if item.type == "sentence"]) >= 12
    assert len([item for item in items if item.type == "choice"]) >= 6


def test_every_sentence_item_has_full_rubric() -> None:
    for item in _l3_items():
        if item.type == "sentence":
            assert item.rubric is not None
            assert item.rubric.keyword_groups


def test_samples_cover_every_sentence_item() -> None:
    sentence_ids = {item.id for item in _l3_items() if item.type == "sentence"}
    samples = json.loads((DATA / "l3_rubric_samples.json").read_text(encoding="utf-8"))
    assert set(samples) == sentence_ids
    for sample in samples.values():
        assert len(sample["pass"]) >= 1
        assert len(sample["fail"]) >= 1


# TASK-DOM-02 adds tests asserting the checker agrees with every sample.
