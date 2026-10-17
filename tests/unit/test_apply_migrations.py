"""Tests for the migration runner using a fake connection (no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.apply_migrations as runner


class FakeTransaction:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> FakeTransaction:
        self._connection.versions_snapshot = set(self._connection.versions)
        self._connection.executed_snapshot = list(self._connection.executed)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            self._connection.versions = set(self._connection.versions_snapshot)
            self._connection.executed = list(self._connection.executed_snapshot)
        return False


class FakeConnection:
    def __init__(
        self, applied: set[str] | None = None, fail_contains: str | None = None
    ) -> None:
        self.versions: set[str] = set(applied or ())
        self.fail_contains = fail_contains
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.versions_snapshot: set[str] = set()
        self.executed_snapshot: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def execute(self, sql: str, *args: Any) -> str:
        if self.fail_contains and self.fail_contains in sql:
            raise RuntimeError("boom")
        self.executed.append((sql, args))
        if args:
            self.versions.add(args[0])
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, str]]:
        return [{"version": version} for version in sorted(self.versions)]

    async def close(self) -> None:
        self.closed = True


def _write(path: Path, name: str, body: str) -> None:
    (path / name).write_text(body, encoding="utf-8")


def test_list_migration_files_sorted_and_sql_only(tmp_path: Path) -> None:
    _write(tmp_path, "002_second.sql", "select 2;")
    _write(tmp_path, "001_first.sql", "select 1;")
    _write(tmp_path, "notes.txt", "ignore me")

    names = [path.name for path in runner.list_migration_files(tmp_path)]

    assert names == ["001_first.sql", "002_second.sql"]


def test_apply_migrations_applies_pending_in_order(tmp_path: Path) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    _write(tmp_path, "002_second.sql", "create table second (id int);")
    connection = FakeConnection()

    applied = asyncio.run(runner.apply_migrations(connection, tmp_path))

    assert applied == ["001_first.sql", "002_second.sql"]
    assert connection.versions == {"001_first.sql", "002_second.sql"}
    sqls = [sql for sql, _ in connection.executed]
    assert runner.CREATE_SCHEMA_MIGRATIONS in sqls
    assert sqls.index("create table first (id int);") < sqls.index(runner.INSERT_VERSION)
    assert sqls.index("create table first (id int);") < sqls.index(
        "create table second (id int);"
    )


def test_apply_migrations_skips_recorded_versions(tmp_path: Path) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    _write(tmp_path, "002_second.sql", "create table second (id int);")
    connection = FakeConnection(applied={"001_first.sql"})

    applied = asyncio.run(runner.apply_migrations(connection, tmp_path))

    assert applied == ["002_second.sql"]


def test_second_run_applies_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    connection = FakeConnection()

    first = asyncio.run(runner.apply_migrations(connection, tmp_path))
    second = asyncio.run(runner.apply_migrations(connection, tmp_path))

    assert first == ["001_first.sql"]
    assert second == []


def test_failing_migration_rolls_back_everything(tmp_path: Path) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    _write(tmp_path, "002_second.sql", "create table second (id int);")
    connection = FakeConnection(fail_contains="create table second")

    with pytest.raises(RuntimeError):
        asyncio.run(runner.apply_migrations(connection, tmp_path))

    assert connection.versions == set()


def test_run_exits_zero_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    connection = FakeConnection()
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(database_url="x"))

    async def fake_connect(*args: Any, **kwargs: Any) -> FakeConnection:
        return connection

    monkeypatch.setattr(runner.asyncpg, "connect", fake_connect)

    assert asyncio.run(runner._run()) == 0
    assert connection.closed


def test_run_exits_one_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "001_first.sql", "create table first (id int);")
    connection = FakeConnection(fail_contains="create table first")
    monkeypatch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(database_url="x"))

    async def fake_connect(*args: Any, **kwargs: Any) -> FakeConnection:
        return connection

    monkeypatch.setattr(runner.asyncpg, "connect", fake_connect)

    assert asyncio.run(runner._run()) == 1
    assert connection.closed
