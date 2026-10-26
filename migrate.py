"""Apply versioned SQL migrations. Run: python migrate.py

Files in migrations/ are named NNN_description.sql and applied in numeric
order. Each file runs in its own transaction and is recorded in the
schema_migrations table, so re-running only applies what is new.

To change the schema, add the next numbered file; never edit one that has
already been applied.
"""
import re
from pathlib import Path

from db import get_conn

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
FILENAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

# Arbitrary constant; serializes concurrent `migrate.py` runs on one database.
LOCK_KEY = 7_203_581_141


def discover(directory=MIGRATIONS_DIR):
    """Return [(version, path)] sorted by version, e.g. ('001_baseline', Path).

    Rejects misnamed files, duplicate numbers, and gaps in the sequence: a
    gap means a migration is missing from this checkout.
    """
    found = []
    for path in sorted(Path(directory).glob("*.sql")):
        match = FILENAME.match(path.name)
        if not match:
            raise ValueError(f"migration filename must look like 001_name.sql: {path.name}")
        found.append((int(match.group(1)), path.stem, path))

    numbers = [n for n, _, _ in found]
    if len(numbers) != len(set(numbers)):
        raise ValueError("duplicate migration number in " + str(directory))
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"migration numbers must run 001..{len(numbers):03d} with no gaps, got {numbers}")

    return [(version, path) for _, version, path in found]


def pending(discovered, applied):
    """Migrations in `discovered` not yet in `applied`, in order.

    Raises if the database records a migration this checkout does not have,
    which means the code is older than the schema it is pointed at.
    """
    known = {version for version, _ in discovered}
    unknown = set(applied) - known
    if unknown:
        raise ValueError(f"database has migrations missing from this checkout: {sorted(unknown)}")
    return [(version, path) for version, path in discovered if version not in applied]


def main():
    discovered = discover()
    with get_conn() as conn:
        with conn.cursor() as cursor:
            # Session-level lock: held across the per-migration commits below.
            cursor.execute("SELECT pg_advisory_lock(%s);", (LOCK_KEY,))
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version    TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );
                    """
                )
                cursor.execute("SELECT version FROM schema_migrations;")
                applied = {row[0] for row in cursor.fetchall()}
            conn.commit()

            todo = pending(discovered, applied)
            if not todo:
                print("Schema up to date")
                return

            for version, path in todo:
                with conn.cursor() as cursor:
                    cursor.execute(path.read_text())
                    cursor.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s);", (version,)
                    )
                conn.commit()
                print(f"Applied {version}")
        except Exception:
            conn.rollback()
            raise
        finally:
            with conn.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s);", (LOCK_KEY,))


if __name__ == "__main__":
    main()
