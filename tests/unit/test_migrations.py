"""Tests for the initial migration SQL and its schema definitions."""

import re
from pathlib import Path

MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "001_init.sql"
DDL_PREFIXES = ("create table", "create index", "alter table")
DATA_TABLES = ("sessions", "messages", "attempts", "level_events")


def _read_sql() -> str:
    assert MIGRATION_PATH.is_file(), "migrations/001_init.sql must exist"
    content = MIGRATION_PATH.read_text(encoding="utf-8")
    assert content.strip()
    return content


def _strip_comments_and_strings(sql: str) -> tuple[str, bool]:
    """Remove line comments and string literals, tracking quote balance."""

    out: list[str] = []
    in_string = False
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if in_string:
            if char == "'":
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            index += 1
            continue
        if char == "-" and index + 1 < length and sql[index + 1] == "-":
            while index < length and sql[index] != "\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out), not in_string


def test_schema_migrations_created_if_not_exists() -> None:
    content = _read_sql()
    assert re.search(
        r"create\s+table\s+if\s+not\s+exists\s+schema_migrations",
        content,
        re.IGNORECASE,
    )


def test_data_tables_created() -> None:
    content = _read_sql()
    for table in DATA_TABLES:
        assert re.search(rf"create\s+table\s+{table}\b", content, re.IGNORECASE), (
            f"Table {table} missing"
        )


def test_check_constraints_present() -> None:
    content = _read_sql()
    assert "char_length(nickname) <= 20" in content
    assert "level between 1 and 3" in content
    assert "role in ('child','bot')" in content
    assert "mode in ('learning','conversation','engagement','support')" in content
    assert "result in ('correct','incorrect','unsure','skipped','revealed')" in content


def test_foreign_keys_cascade() -> None:
    content = _read_sql()
    cascade_matches = re.findall(
        r"references\s+sessions\s*\(\s*id\s*\)\s+on\s+delete\s+cascade",
        content,
        re.IGNORECASE,
    )
    assert len(cascade_matches) == 3, (
        f"Expected 3 cascading foreign keys to sessions, found {len(cascade_matches)}"
    )


def test_indexes_present() -> None:
    content = _read_sql()
    assert re.search(
        r"create\s+index\s+messages_session_idx\s+on\s+messages\s*\(\s*session_id\s*,\s*id\s+desc\s*\)",
        content,
        re.IGNORECASE,
    )
    assert re.search(
        r"create\s+index\s+attempts_session_idx\s+on\s+attempts\s*\(\s*session_id\s*,\s*id\s+desc\s*\)",
        content,
        re.IGNORECASE,
    )


def test_rls_enabled_and_no_policies() -> None:
    content = _read_sql()
    for table in DATA_TABLES:
        assert re.search(
            rf"alter\s+table\s+{table}\s+enable\s+row\s+level\s+security",
            content,
            re.IGNORECASE,
        ), f"RLS not enabled on {table}"
    assert not re.search(r"create\s+policy\b", content, re.IGNORECASE)


def test_sql_statement_syntax_is_well_formed() -> None:
    content = _read_sql()
    stripped, quotes_balanced = _strip_comments_and_strings(content)
    assert quotes_balanced, "Unbalanced string literal (odd number of single quotes)"
    assert stripped.count("(") == stripped.count(")"), "Unbalanced parentheses"

    statements = [stmt.strip() for stmt in stripped.split(";") if stmt.strip()]
    assert len(statements) >= 11, f"Expected at least 11 DDL statements, got {len(statements)}"
    assert stripped.count(";") == len(statements), "Every statement must end with a semicolon"

    for statement in statements:
        lowered = statement.lower()
        assert lowered.startswith(DDL_PREFIXES), f"Unexpected statement: {statement[:40]!r}"
