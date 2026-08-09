"""
Resolves a bare service_name string (all telemetry only carries a name, never
a UUID) to the `services.id` UUID that incident_services/incident_evidence
foreign keys require. Telemetry can arrive for a service that's never been
seen before (a new deploy, a typo'd name, an experimental service) - rather
than dropping that data, an unseen name is auto-registered on first sight.

Backed by psycopg (sync), run through a thread executor like the ClickHouse
writer, with an in-process cache so steady-state operation doesn't hit
Postgres on every single event - only once per (workspace, service) ever.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

import psycopg


class ServiceRegistry(Protocol):
    async def resolve(self, workspace_id: uuid.UUID, service_name: str) -> uuid.UUID: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class PostgresServiceRegistry:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._conn: psycopg.Connection | None = None
        self._cache: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._conn = await loop.run_in_executor(
            None, lambda: psycopg.connect(self._database_url, autocommit=True)
        )

    async def stop(self) -> None:
        if self._conn is not None:
            self._conn.close()

    async def resolve(self, workspace_id: uuid.UUID, service_name: str) -> uuid.UUID:
        cache_key = (workspace_id, service_name)
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with self._lock:
            # Re-check after acquiring the lock - another coroutine may have
            # resolved (and cached) the same service while we were waiting.
            if cache_key in self._cache:
                return self._cache[cache_key]

            loop = asyncio.get_running_loop()
            service_id = await loop.run_in_executor(
                None, self._resolve_or_create, workspace_id, service_name
            )
            self._cache[cache_key] = service_id
            return service_id

    def _resolve_or_create(self, workspace_id: uuid.UUID, service_name: str) -> uuid.UUID:
        assert self._conn is not None
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM services WHERE workspace_id = %s AND name = %s",
                (str(workspace_id), service_name),
            )
            row = cur.fetchone()
            if row is not None:
                return uuid.UUID(str(row[0]))

            cur.execute(
                """
                INSERT INTO services (workspace_id, name)
                VALUES (%s, %s)
                ON CONFLICT (workspace_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (str(workspace_id), service_name),
            )
            new_id = cur.fetchone()[0]
            return uuid.UUID(str(new_id))
