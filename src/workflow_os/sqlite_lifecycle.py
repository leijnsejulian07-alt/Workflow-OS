from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def managed_connection(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Use sqlite transaction semantics and always close the handle afterwards.

    sqlite3.Connection.__exit__ commits or rolls back but does not close the
    underlying connection. Explicit close is required for deterministic Windows
    cleanup and bounded handle usage in long-running workers.
    """
    try:
        with connection:
            yield connection
    finally:
        connection.close()
