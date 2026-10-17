from __future__ import annotations

import pytest

from app.domain.safety import validate_reply
from app.fallbacks.templates import EVENT_MODES, TEMPLATES, pick_template

MEANINGFUL = [
    (event, mode, level)
    for event, modes in EVENT_MODES.items()
    for mode in modes
    for level in (1, 2, 3)
]


def test_every_event_is_defined() -> None:
    assert set(EVENT_MODES) == set(TEMPLATES)


@pytest.mark.parametrize(("event", "mode", "level"), MEANINGFUL)
def test_every_template_passes_validate_reply(event: str, mode: str, level: int) -> None:
    rendered = pick_template(mode, level, event, seed=0, nickname="Sam")  # type: ignore[arg-type]
    ok, reasons = validate_reply(rendered, level)
    assert ok, (event, mode, level, rendered, reasons)


@pytest.mark.parametrize(("event", "mode", "level"), MEANINGFUL)
def test_meaningful_combinations_have_at_least_two_variants(
    event: str, mode: str, level: int
) -> None:
    seen = {
        pick_template(mode, level, event, seed=seed, nickname="Sam")  # type: ignore[arg-type]
        for seed in range(8)
    }
    assert len(seen) >= 2


def test_pick_template_is_deterministic() -> None:
    first = pick_template("learning", 1, "correct", seed=42, nickname="Sam")
    second = pick_template("learning", 1, "correct", seed=42, nickname="Sam")
    assert first == second


def test_pick_template_varies_with_seed() -> None:
    outputs = {
        pick_template("learning", 2, "correct", seed=seed, nickname="Sam") for seed in range(4)
    }
    assert len(outputs) >= 2


def test_nickname_is_inserted() -> None:
    rendered = pick_template("learning", 1, "greeting", seed=0, nickname="Sam")
    assert "Sam" in rendered


def test_nickname_defaults_when_missing() -> None:
    rendered = pick_template("learning", 1, "greeting", seed=0, nickname=None)
    assert "{" not in rendered
    assert "}" not in rendered


def test_nickname_with_braces_cannot_break_the_template() -> None:
    rendered = pick_template("learning", 1, "greeting", seed=0, nickname="{evil}")
    assert "{nickname}" not in rendered
    assert "evil" in rendered


def test_meaningless_combination_falls_back_to_generic() -> None:
    rendered = pick_template("conversation", 1, "correct", seed=0, nickname="Sam")
    ok, _ = validate_reply(rendered, 1)
    assert ok is True
