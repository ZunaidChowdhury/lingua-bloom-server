"""Guard against string-built SQL in the PostgreSQL repository."""

from __future__ import annotations

import ast
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "app" / "repositories" / "postgres.py"
TEXT = SOURCE.read_text(encoding="utf-8")

CONCAT = re.compile(r"[\"']\s*\+|\+\s*[\"']")
SQL_MARKER = re.compile(
    r"\b(select|insert|update|delete|from|where|values|join|order by|limit)\b",
    re.IGNORECASE,
)


def _fstring_literals(source: str) -> list[str]:
    tree = ast.parse(source)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = [
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ]
            literals.append("".join(parts))
    return literals


def test_no_fstring_sql() -> None:
    for literal in _fstring_literals(TEXT):
        assert SQL_MARKER.search(literal) is None


def test_no_format_calls() -> None:
    assert ".format(" not in TEXT


def test_no_string_concatenation() -> None:
    assert CONCAT.findall(TEXT) == []


def test_queries_use_positional_placeholders() -> None:
    assert "$1" in TEXT
