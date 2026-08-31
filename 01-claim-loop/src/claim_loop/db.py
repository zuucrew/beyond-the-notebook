"""Connection pool and the transaction helper.

Everything in this project goes through transaction(). The pool is created once
and lazily -- pool size is the number that kills you on deploy day, so it is
worth having it visible in one place rather than hidden in a framework.
"""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DATABASE_URL

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # max_size is the number to remember. On Cloud Run this multiplies by
        # the instance count and must stay under Cloud SQL's max_connections.
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
        )
        _pool.wait(timeout=10)
    return _pool


@contextmanager
def transaction():
    """One database transaction.

    Commits on clean exit, rolls back on exception. Row locks taken inside are
    held until this block ends -- which is the entire reason claiming work is
    correct. See queue.claim_next_for_extraction.
    """
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
