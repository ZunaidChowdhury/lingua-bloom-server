"""Delete expired sessions and print the count.

Run with: python scripts/purge_expired.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncpg  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.repositories.postgres import PostgresRepository  # noqa: E402


class PurgeRepository(Protocol):
    """Minimal storage contract the purge needs."""

    async def purge_expired(self, now: datetime) -> int: ...

    async def count_expired(self, now: datetime) -> int: ...


async def purge_expired_sessions(
    repository: PurgeRepository, now: datetime, dry_run: bool = False
) -> int:
    """Delete expired sessions, or count them when *dry_run* is true."""

    if dry_run:
        return await repository.count_expired(now)
    return await repository.purge_expired(now)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Purge expired LinguaBloom sessions.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the number of expired sessions without deleting them.",
    )
    return parser


async def _run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=2, statement_cache_size=0
    )
    if pool is None:
        print("Purge failed: could not connect to the database.", file=sys.stderr)
        return 1
    try:
        repository = PostgresRepository(pool)
        count = await purge_expired_sessions(
            repository, datetime.now(UTC), dry_run=args.dry_run
        )
    except Exception as exc:
        print(f"Purge failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await pool.close()
    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {count} expired session(s).")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
