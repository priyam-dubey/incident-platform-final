"""
Minimal, dependency-light migration runner.

Design goals:
- Plain, reviewable SQL files (packages/db/migrations/NNNN_name.sql) - no ORM
  migration DSL to learn, no hidden magic.
- Idempotent: each migration is applied at most once, tracked via a checksum
  in schema_migrations so a file can never be silently re-applied after edit
  (edits are detected and rejected loudly instead of applied twice).
- Transactional: each migration file runs inside a single transaction, so a
  partial failure never leaves the schema half-migrated.

Usage:
    python -m migrate up            # apply all pending migrations
    python -m migrate status        # show applied vs pending
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class Migration:
    version: str  # e.g. "0001_init"
    path: Path
    sql: str
    checksum: str

    @staticmethod
    def load(path: Path) -> "Migration":
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        version = path.stem
        return Migration(version=version, path=path, sql=sql, checksum=checksum)


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No migration files found in {migrations_dir}")
    return [Migration.load(f) for f in files]


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env and set it, "
            "or export it directly before running migrations."
        )
    return url


def fetch_applied(conn: psycopg.Connection) -> dict[str, str]:
    """Returns {version: checksum} for every migration already recorded."""
    with conn.cursor() as cur:
        cur.execute(BOOTSTRAP_SQL)
        cur.execute("SELECT version, checksum FROM schema_migrations")
        return dict(cur.fetchall())


def apply_migration(conn: psycopg.Connection, migration: Migration) -> None:
    with conn.cursor() as cur:
        cur.execute(migration.sql)
        cur.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
            (migration.version, migration.checksum),
        )
    conn.commit()


def run_up(migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Applies every pending migration in order. Returns list of versions applied."""
    migrations = discover_migrations(migrations_dir)
    applied_versions: list[str] = []

    with psycopg.connect(get_database_url()) as conn:
        applied = fetch_applied(conn)

        for migration in migrations:
            if migration.version in applied:
                recorded_checksum = applied[migration.version]
                if recorded_checksum != migration.checksum:
                    raise RuntimeError(
                        f"Migration {migration.version} was already applied but its "
                        f"file content has changed since (checksum mismatch). "
                        f"Never edit an applied migration - write a new one instead."
                    )
                continue

            print(f"Applying {migration.version} ...")
            apply_migration(conn, migration)
            applied_versions.append(migration.version)

    return applied_versions


def run_status(migrations_dir: Path = MIGRATIONS_DIR) -> None:
    migrations = discover_migrations(migrations_dir)
    with psycopg.connect(get_database_url()) as conn:
        applied = fetch_applied(conn)

    for migration in migrations:
        state = "APPLIED" if migration.version in applied else "pending"
        print(f"  [{state:7}] {migration.version}")


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "up"

    if command == "up":
        applied = run_up()
        if applied:
            print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
        else:
            print("Nothing to apply - schema is up to date.")
        return 0

    if command == "status":
        run_status()
        return 0

    print(f"Unknown command: {command}. Use 'up' or 'status'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
