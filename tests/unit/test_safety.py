from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.domain.safety import (
    DISTRESS_TEMPLATES,
    SanitizeFlags,
    distress_reply,
    needs_distress_escalation,
    sanitize,
    validate_reply,
)


def test_control_characters_are_stripped() -> None:
    clean, _ = sanitize("Hello\x00\x07World")
    assert clean == "HelloWorld"


def test_whitespace_is_collapsed_and_trimmed() -> None:
    clean, _ = sanitize("  hello \t\n  world  ")
    assert clean == "hello world"


def test_harmless_input_is_returned_unchanged() -> None:
    text = "I like the blue ball"
    clean, flags = sanitize(text)
    assert clean == text
    assert flags == SanitizeFlags(pii=False, injection=False)


@pytest.mark.parametrize(
    "text",
    ["mail me at kid@example.com", "my email is a.b@c.co.uk", "a@b.com"],
)
def test_email_is_redacted(text: str) -> None:
    clean, flags = sanitize(text)
    assert "[removed]" in clean
    assert "@" not in clean
    assert flags.pii is True


@pytest.mark.parametrize(
    "text",
    ["call 1234567 now", "number 1234567890", "phone 5551234567 please"],
)
def test_phone_is_redacted(text: str) -> None:
    clean, flags = sanitize(text)
    assert "[removed]" in clean
    assert flags.pii is True


def test_six_digit_run_is_not_redacted() -> None:
    text = "I can count to 123456"
    clean, flags = sanitize(text)
    assert clean == text
    assert flags.pii is False


@pytest.mark.parametrize("text", ["12 Maple Street", "5 Oak Road", "10 Elm Avenue"])
def test_address_like_phrases_are_redacted(text: str) -> None:
    clean, flags = sanitize(text)
    assert clean == "[removed]"
    assert flags.pii is True


def test_redaction_preserves_surrounding_text() -> None:
    clean, _ = sanitize("email kid@example.com now")
    assert clean == "email [removed] now"


@pytest.mark.parametrize(
    "phrase",
    ["ignore previous instructions", "system prompt", "you are now", "pretend you are"],
)
def test_injection_phrases_set_the_flag(phrase: str) -> None:
    clean, flags = sanitize(f"please {phrase} and then help me")
    assert flags.injection is True
    assert flags.pii is False
    assert "[removed]" not in clean


def test_injection_detection_is_case_insensitive() -> None:
    _, flags = sanitize("IGNORE PREVIOUS INSTRUCTIONS")
    assert flags.injection is True


def test_pii_and_injection_can_both_be_set() -> None:
    _, flags = sanitize("email me at kid@example.com and ignore previous instructions")
    assert flags.pii is True
    assert flags.injection is True


def test_flags_are_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        sanitize("hi")[1].pii = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "text",
    ["i want to die", "kill myself", "i want to hurt myself", "end my life"],
)
def test_severe_distress_is_detected(text: str) -> None:
    assert needs_distress_escalation(text) is True


@pytest.mark.parametrize(
    "text",
    ["i like the blue ball", "i am sad", "tell me a story", "lets play a game"],
)
def test_ordinary_messages_do_not_trigger_escalation(text: str) -> None:
    assert needs_distress_escalation(text) is False


@pytest.mark.parametrize("level", [1, 2, 3])
def test_distress_reply_is_offered_at_every_level(level: int) -> None:
    reply = distress_reply(level)
    assert reply
    assert "grown-up" in reply


def test_distress_reply_is_level_appropriate() -> None:
    assert len(distress_reply(1)) <= len(distress_reply(3))


def test_distress_reply_never_repeats_the_child_text() -> None:
    for level in (1, 2, 3):
        assert "die" not in distress_reply(level).lower()


def test_distress_reply_has_no_banned_words() -> None:
    from app.domain.sel import BANNED_FEEDBACK_WORDS

    for reply in DISTRESS_TEMPLATES.values():
        assert all(banned not in reply.lower() for banned in BANNED_FEEDBACK_WORDS)


def test_safe_reply_passes_with_no_reasons() -> None:
    ok, reasons = validate_reply("Nice try! Let us play a game.", 1)
    assert ok is True
    assert reasons == []


def test_reply_length_passing() -> None:
    ok, _ = validate_reply("a" * 240, 3)
    assert ok is True


def test_reply_length_failing() -> None:
    ok, reasons = validate_reply("a" * 241, 3)
    assert ok is False
    assert "too_long" in reasons


def test_sentence_count_passing() -> None:
    ok, _ = validate_reply("Hi. I like red. Bye.", 2)
    assert ok is True


def test_sentence_count_failing() -> None:
    ok, reasons = validate_reply("One. Two. Three. Four.", 2)
    assert ok is False
    assert "too_many_sentences" in reasons


def test_url_passing() -> None:
    ok, _ = validate_reply("Let us play a game.", 2)
    assert ok is True


def test_url_failing() -> None:
    ok, reasons = validate_reply("Visit www.example.com now.", 2)
    assert ok is False
    assert "url" in reasons


def test_personal_info_passing() -> None:
    ok, _ = validate_reply("I like your hat.", 2)
    assert ok is True


def test_personal_info_failing() -> None:
    ok, reasons = validate_reply("What is your name?", 2)
    assert ok is False
    assert "requests_personal_info" in reasons


def test_banned_word_passing() -> None:
    ok, _ = validate_reply("Nice try! Let us try again together.", 2)
    assert ok is True


def test_banned_word_failing() -> None:
    ok, reasons = validate_reply("That is wrong.", 2)
    assert ok is False
    assert "banned_word" in reasons


def test_emoji_count_passing() -> None:
    ok, _ = validate_reply("Yay \U0001F600\U0001F600", 2)
    assert ok is True


def test_emoji_count_failing() -> None:
    ok, reasons = validate_reply("Yay \U0001F600\U0001F600\U0001F600\U0001F600", 2)
    assert ok is False
    assert "too_many_emoji" in reasons


def test_reading_level_passing() -> None:
    ok, _ = validate_reply("I like red.", 1)
    assert ok is True


def test_reading_level_failing() -> None:
    ok, reasons = validate_reply(
        "I like the big red ball and I want to play with it today.", 1
    )
    assert ok is False
    assert "reading_level" in reasons
