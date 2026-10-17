"""Apply ordered SQL migrations to the database and record their versions.

Run with: python scripts/apply_migrations.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncpg  # noqa: E402

from app.core.config import get_settings  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

CREATE_SCHEMA_MIGRATIONS = """
create table if not exists schema_migrations (
  version     text primary key,
  applied_at  timestamptz not null default now()
)
"""

INSERT_VERSION = "insert into schema_migrations (version) values ($1)"
SELECT_VERSIONS = "select version from schema_migrations"


def list_migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return the .sql migration files ordered by filename."""

    return sorted(migrations_dir.glob("*.sql"), key=lambda path: path.name)


async def apply_migrations(
    connection: asyncpg.Connection, migrations_dir: Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply pending migrations in one transaction; return the versions applied.

    The whole run is a single transaction, so a failure rolls back every change.
    """

    applied: list[str] = []
    async with connection.transaction():
        await connection.execute(CREATE_SCHEMA_MIGRATIONS)
        rows = await connection.fetch(SELECT_VERSIONS)
        recorded = {row["version"] for row in rows}
        for path in list_migration_files(migrations_dir):
            version = path.name
            if version in recorded:
                continue
            await connection.execute(path.read_text(encoding="utf-8"))
            await connection.execute(INSERT_VERSION, version)
            applied.append(version)
    return applied


async def _run() -> int:
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        applied = await apply_migrations(connection, MIGRATIONS_DIR)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await connection.close()
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    else:
        print("No pending migrations.")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
