"""
Tests for the migration runner's core logic: discovery, checksum tracking,
and change detection. These test the pure logic (file discovery, checksumming,
apply/skip decisions) without a live Postgres connection, using a fake
connection object that mimics the small slice of the psycopg API we use.
Integration against a real Postgres instance is exercised via
docker-compose in CI (see .github/workflows/ci.yml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import migrate  # noqa: E402


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_init.sql").write_text("CREATE TABLE foo (id INT);")
    (d / "0002_add_bar.sql").write_text("ALTER TABLE foo ADD COLUMN bar TEXT;")
    return d


def test_discover_migrations_orders_by_filename(migrations_dir: Path) -> None:
    migrations = migrate.discover_migrations(migrations_dir)
    versions = [m.version for m in migrations]
    assert versions == ["0001_init", "0002_add_bar"]


def test_discover_migrations_raises_when_empty(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(RuntimeError, match="No migration files found"):
        migrate.discover_migrations(empty_dir)


def test_migration_checksum_is_stable_for_same_content(migrations_dir: Path) -> None:
    m1 = migrate.Migration.load(migrations_dir / "0001_init.sql")
    m2 = migrate.Migration.load(migrations_dir / "0001_init.sql")
    assert m1.checksum == m2.checksum


def test_migration_checksum_changes_when_content_changes(migrations_dir: Path) -> None:
    path = migrations_dir / "0001_init.sql"
    original = migrate.Migration.load(path)

    path.write_text("CREATE TABLE foo (id INT); -- edited")
    edited = migrate.Migration.load(path)

    assert original.checksum != edited.checksum


class _FakeCursor:
    def __init__(self, store: dict[str, str]):
        self._store = store
        self._last_result: list[tuple[str, str]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT version, checksum"):
            self._last_result = list(self._store.items())
        elif normalized.startswith("INSERT INTO schema_migrations"):
            version, checksum = params
            self._store[version] = checksum
        # CREATE TABLE IF NOT EXISTS / arbitrary migration SQL: no-op for the fake.

    def fetchall(self) -> list[tuple[str, str]]:
        return self._last_result

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConnection:
    """Mimics the subset of psycopg.Connection used by migrate.py."""

    def __init__(self, initial_applied: dict[str, str] | None = None):
        self._store: dict[str, str] = dict(initial_applied or {})
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._store)

    def commit(self) -> None:
        self.committed = True


def test_fetch_applied_returns_recorded_versions() -> None:
    conn = _FakeConnection(initial_applied={"0001_init": "abc123"})
    applied = migrate.fetch_applied(conn)  # type: ignore[arg-type]
    assert applied == {"0001_init": "abc123"}


def test_apply_migration_records_version_and_commits(migrations_dir: Path) -> None:
    conn = _FakeConnection()
    migration = migrate.discover_migrations(migrations_dir)[0]

    migrate.apply_migration(conn, migration)  # type: ignore[arg-type]

    assert conn._store[migration.version] == migration.checksum
    assert conn.committed is True


def test_run_up_skips_already_applied_with_matching_checksum(
    migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = migrate.Migration.load(migrations_dir / "0001_init.sql")
    conn = _FakeConnection(initial_applied={first.version: first.checksum})

    monkeypatch.setattr(migrate, "get_database_url", lambda: "postgresql://fake")
    monkeypatch.setattr(migrate.psycopg, "connect", lambda *_a, **_kw: _ConnCtx(conn))

    applied = migrate.run_up(migrations_dir)

    assert applied == ["0002_add_bar"]


def test_run_up_raises_on_checksum_mismatch(
    migrations_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _FakeConnection(initial_applied={"0001_init": "stale-checksum-from-before-edit"})

    monkeypatch.setattr(migrate, "get_database_url", lambda: "postgresql://fake")
    monkeypatch.setattr(migrate.psycopg, "connect", lambda *_a, **_kw: _ConnCtx(conn))

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate.run_up(migrations_dir)


class _ConnCtx:
    """Fakes the `with psycopg.connect(...) as conn:` context manager protocol."""

    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    def __enter__(self) -> _FakeConnection:
        return self._conn

    def __exit__(self, *exc: object) -> None:
        return None
