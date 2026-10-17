"""Deterministic item selection and choice shuffling (FR-1.6)."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence

from app.domain.curriculum.models import Choice, Item

EXCLUDE_WINDOW = 10
WEAK_ACCURACY_THRESHOLD = 0.5
WEAK_WEIGHT = 2
NORMAL_WEIGHT = 1


def _skill_weight(skill: str, skill_stats: Mapping[str, float]) -> int:
    accuracy = skill_stats.get(skill)
    if accuracy is not None and accuracy < WEAK_ACCURACY_THRESHOLD:
        return WEAK_WEIGHT
    return NORMAL_WEIGHT


class ItemSelector:
    """Selects the next curriculum item from a loaded bank, deterministically."""

    def __init__(self, bank: Mapping[int, Sequence[Item]]) -> None:
        self._bank = bank

    def select_next(
        self,
        level: int,
        skill_stats: Mapping[str, float],
        recent_item_ids: Sequence[str],
        seed: int,
    ) -> Item:
        pool = list(self._bank[level])
        recent = list(recent_item_ids)[-EXCLUDE_WINDOW:]
        recent_set = set(recent)
        available = [item for item in pool if item.id not in recent_set]

        if not available:
            order = {item_id: index for index, item_id in enumerate(recent)}
            available = sorted(pool, key=lambda item: order.get(item.id, -1))[:1]

        weights = [_skill_weight(item.skill, skill_stats) for item in available]
        return random.Random(seed).choices(available, weights=weights, k=1)[0]


def shuffled_choices(item: Item, session_id: str) -> list[Choice]:
    """Return the item's choices in a stable order for one session and item."""

    choices = list(item.choices)
    digest = hashlib.sha256(f"{session_id}:{item.id}".encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    rng.shuffle(choices)
    return choices
