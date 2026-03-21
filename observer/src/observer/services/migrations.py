"""Schema migration runner for observer.

Tracks applied migrations in a ``schema_version`` table (managed outside
SQLAlchemy metadata so it never conflicts with ``create_all``). Migrations
are Python functions registered via :func:`migration` and run in version
order.

New installs get the latest schema from ``Base.metadata.create_all()`` and
start at the highest migration version. Existing installs run pending
migrations via ``observer db migrate``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    description: str
    fn: Callable[[Engine], None]


# Migration registry — populated by @migration decorator
_registry: dict[int, Migration] = {}


def migration(version: int, description: str) -> Callable:
    """Register a migration function.

    Each migration receives a SQLAlchemy Engine and should use
    ``engine.begin()`` for transactional DDL operations.
    """

    def decorator(fn: Callable[[Engine], None]) -> Callable[[Engine], None]:
        if version in _registry:
            msg = f"Duplicate migration version: {version}"
            raise ValueError(msg)
        _registry[version] = Migration(version=version, description=description, fn=fn)
        return fn

    return decorator


def get_current_version(engine: Engine) -> int:
    """Return the current schema version, or 0 if untracked."""
    with engine.connect() as conn:
        has_table = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_version'")
        ).fetchone()
        if not has_table:
            return 0
        row = conn.execute(text("SELECT version FROM schema_version")).fetchone()
        return row[0] if row else 0


def get_latest_version() -> int:
    """Return the highest registered migration version."""
    return max(_registry) if _registry else 0


def get_pending(engine: Engine) -> list[Migration]:
    """Return migrations that haven't been applied yet, in order."""
    current = get_current_version(engine)
    return sorted(
        (m for m in _registry.values() if m.version > current),
        key=lambda m: m.version,
    )


def _ensure_version_table(engine: Engine) -> None:
    """Create the schema_version table if it doesn't exist."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                "  version INTEGER NOT NULL,"
                "  applied_at TIMESTAMP NOT NULL DEFAULT now()"
                ")"
            )
        )


def _set_version(engine: Engine, version: int) -> None:
    """Set the schema version (upsert — single row)."""
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT 1 FROM schema_version")).fetchone()
        if existing:
            conn.execute(text("UPDATE schema_version SET version = :v, applied_at = now()"), {"v": version})
        else:
            conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version})


def stamp(engine: Engine) -> None:
    """Mark the database as current without running migrations.

    Used for new installs where ``create_all()`` already built the
    latest schema.
    """
    latest = get_latest_version()
    if latest == 0:
        return
    _ensure_version_table(engine)
    _set_version(engine, latest)


def run_pending(engine: Engine) -> list[Migration]:
    """Run all pending migrations in order. Returns the list of applied migrations."""
    pending = get_pending(engine)
    if not pending:
        return []

    _ensure_version_table(engine)

    applied: list[Migration] = []
    for m in pending:
        logger.info("Running migration %03d: %s", m.version, m.description)
        m.fn(engine)
        _set_version(engine, m.version)
        applied.append(m)
        logger.info("Applied migration %03d", m.version)

    return applied


def needs_migration(engine: Engine) -> bool:
    """Check if there are pending migrations."""
    return len(get_pending(engine)) > 0


# Import migrations package to populate the registry.
import observer.migrations  # noqa: E402, F401
