"""Opaque session tokens. Only the SHA-256 hash is stored or compared."""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def generate_token() -> str:
    """Return a new URL-safe opaque token (32 random bytes)."""

    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the hex SHA-256 digest used for storage and lookup."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
