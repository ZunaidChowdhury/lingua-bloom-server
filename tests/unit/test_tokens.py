"""Token generation and hashing."""

from __future__ import annotations

import hashlib
import string

from app.core.tokens import generate_token, hash_token

URLSAFE = set(string.ascii_letters + string.digits + "-_")


def test_generate_token_is_urlsafe_and_long() -> None:
    token = generate_token()
    assert isinstance(token, str)
    assert len(token) >= 32
    assert set(token) <= URLSAFE


def test_generate_token_is_random() -> None:
    assert generate_token() != generate_token()


def test_hash_token_is_sha256_hex() -> None:
    token = "example-token"
    assert hash_token(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert len(hash_token(token)) == 64


def test_hash_token_is_deterministic_and_not_the_token() -> None:
    token = generate_token()
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token
