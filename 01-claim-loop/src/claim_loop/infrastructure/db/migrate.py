"""Migration runner.

Numbered .sql files, applied in order, recorded in schema_migrations. About
thirty lines, which is the point -- a migration is a file and a discipline, not
a framework.
"""
from ...config import MIGRATIONS_DIR
from .pool import transaction

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def applied_versions() -> set[str]:
    with transaction() as conn:
        conn.execute(_CREATE_TABLE)
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r["version"] for r in rows}


def pending() -> list:
    done = applied_versions()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.stem not in done]


def migrate_up() -> list[str]:
    """Apply each pending migration in its own transaction.

    Per file, not per run: a migration that fails leaves the ones before it
    applied, and you fix that file rather than replaying everything.
    """
    applied = []
    for path in pending():
        with transaction() as conn:
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,)
            )
        applied.append(path.stem)
    return applied
