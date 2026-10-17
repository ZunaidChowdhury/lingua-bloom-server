"""Input safety: sanitisation, PII redaction, and injection flags (FR-6.1, FR-6.2, FR-6.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.modes import detect_signals
from app.domain.sel import BANNED_FEEDBACK_WORDS

WHITESPACE_CONTROLS = re.compile(r"[\t\n\r\f\v]")
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
WHITESPACE = re.compile(r"\s+")

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"\d{7,}")
ADDRESS_PATTERN = re.compile(
    r"\b\d+\s+(?:[A-Za-z]+\s+)?(?:street|road|avenue)\b",
    re.IGNORECASE,
)

INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore your instructions",
    "ignore all previous",
    "system prompt",
    "you are now",
    "pretend you are",
)

PII_PLACEHOLDER = "[removed]"


@dataclass(frozen=True)
class SanitizeFlags:
    pii: bool
    injection: bool


def _collapse(text: str) -> str:
    without_soft_controls = WHITESPACE_CONTROLS.sub(" ", text)
    without_controls = CONTROL_CHARS.sub("", without_soft_controls)
    return WHITESPACE.sub(" ", without_controls).strip()


def _redact_pii(text: str) -> tuple[str, bool]:
    redacted = EMAIL_PATTERN.sub(PII_PLACEHOLDER, text)
    redacted = ADDRESS_PATTERN.sub(PII_PLACEHOLDER, redacted)
    redacted = PHONE_PATTERN.sub(PII_PLACEHOLDER, redacted)
    return redacted, redacted != text


def _has_injection(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in INJECTION_PATTERNS)


def sanitize(text: str) -> tuple[str, SanitizeFlags]:
    """Clean one child message and report the PII and injection flags."""

    cleaned = _collapse(text)
    clean_text, has_pii = _redact_pii(cleaned)
    flags = SanitizeFlags(pii=has_pii, injection=_has_injection(cleaned))
    return clean_text, flags


DISTRESS_TEMPLATES: dict[int, str] = {
    1: "Please tell a grown-up you trust.",
    2: "I want you to be safe. Please talk to a grown-up you trust.",
    3: "Thank you for telling me. Please talk to a grown-up you trust, they can help.",
}


def needs_distress_escalation(text: str) -> bool:
    """True when the message suggests serious distress or danger (FR-3.5)."""

    return detect_signals(text).severe_distress


def distress_reply(level: int) -> str:
    """A short, kind, deterministic reply that avoids the LLM and logs no child text."""

    if level <= 1:
        return DISTRESS_TEMPLATES[1]
    if level == 2:
        return DISTRESS_TEMPLATES[2]
    return DISTRESS_TEMPLATES[3]


MAX_REPLY_CHARS = 240
MAX_SENTENCES = 3
MAX_EMOJI = 3
MAX_AVG_WORDS_BY_LEVEL = {1: 6, 2: 8, 3: 12}

SENTENCE_SPLIT = re.compile(r"[.!?]+")
URL_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|org|net|io|co|edu|gov|app)\b)",
    re.IGNORECASE,
)
PERSONAL_INFO_PATTERN = re.compile(
    r"\byour\s+(name|address|school|phone|phone number|password)\b",
    re.IGNORECASE,
)
BANNED_WORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(BANNED_FEEDBACK_WORDS)) + r")\b",
    re.IGNORECASE,
)
EMOJI_PATTERN = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")


def _sentences(reply: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(reply) if part.strip()]


def _reading_limit(level: int) -> int:
    if level <= 1:
        return MAX_AVG_WORDS_BY_LEVEL[1]
    if level == 2:
        return MAX_AVG_WORDS_BY_LEVEL[2]
    return MAX_AVG_WORDS_BY_LEVEL[3]


def validate_reply(reply: str, level: int) -> tuple[bool, list[str]]:
    """Check one reply against the output rules (FR-6.3). Returns (ok, reasons)."""

    reasons: list[str] = []
    if len(reply) > MAX_REPLY_CHARS:
        reasons.append("too_long")

    sentences = _sentences(reply)
    if len(sentences) > MAX_SENTENCES:
        reasons.append("too_many_sentences")
    if URL_PATTERN.search(reply):
        reasons.append("url")
    if PERSONAL_INFO_PATTERN.search(reply):
        reasons.append("requests_personal_info")
    if BANNED_WORD_PATTERN.search(reply):
        reasons.append("banned_word")
    if len(EMOJI_PATTERN.findall(reply)) > MAX_EMOJI:
        reasons.append("too_many_emoji")
    if sentences:
        average = len(reply.split()) / len(sentences)
        if average > _reading_limit(level):
            reasons.append("reading_level")

    return (not reasons, reasons)
