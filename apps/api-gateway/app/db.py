from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    return ConnectionPool(
        database_url, min_size=min_size, max_size=max_size,
        kwargs={"row_factory": dict_row}, open=True,
    )
