"""Boot-time SQLite schema migrations for local pi-memory databases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pi_memory.constants import (
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_PENDING,
    SOURCE_ORIGIN_UNKNOWN,
)

CURRENT_SQLITE_SCHEMA_VERSION = 7


@dataclass(frozen=True)
class SQLiteMigration:
    version: int
    migrate: Callable[[Connection], None]


def run_sqlite_migrations(connection: Connection) -> None:
    """Apply pending SQLite migrations and advance PRAGMA user_version."""
    current_version = sqlite_user_version(connection)
    for migration in SQLITE_MIGRATIONS:
        if migration.version <= current_version:
            continue
        migration.migrate(connection)
        set_sqlite_user_version(connection, migration.version)


def sqlite_user_version(connection: Connection) -> int:
    """Return the SQLite PRAGMA user_version for this database."""
    return int(connection.execute(text("PRAGMA user_version")).scalar_one())


def set_sqlite_user_version(connection: Connection, version: int) -> None:
    """Set the SQLite PRAGMA user_version for this database."""
    connection.execute(text(f"PRAGMA user_version = {version}"))


def _add_transcript_lineage(connection: Connection) -> None:
    columns = _sqlite_table_columns(connection, "transcripts")
    if not columns:
        return
    if "parent_transcript_path" not in columns:
        connection.execute(text("ALTER TABLE transcripts ADD COLUMN parent_transcript_path VARCHAR"))
    if "parent_transcript_id" not in columns:
        connection.execute(
            text(
                """
                ALTER TABLE transcripts
                ADD COLUMN parent_transcript_id INTEGER REFERENCES transcripts(id) ON DELETE SET NULL
                """,
            ),
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_transcripts_parent_transcript_id ON transcripts (parent_transcript_id)"),
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_transcripts_parent_transcript_path
            ON transcripts (parent_transcript_path)
            """,
        ),
    )


def _add_activity_source_origin(connection: Connection) -> None:
    columns = _sqlite_table_columns(connection, "activity_units")
    if not columns:
        return
    if "source_origin" not in columns:
        connection.execute(
            text(
                f"""
                ALTER TABLE activity_units
                ADD COLUMN source_origin VARCHAR DEFAULT '{SOURCE_ORIGIN_UNKNOWN}' NOT NULL
                """,
            ),
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_activity_units_source_origin ON activity_units (source_origin)"),
    )


def _add_activity_text(connection: Connection) -> None:
    columns = _sqlite_table_columns(connection, "activity_units")
    if not columns:
        return
    if "activity_text" not in columns:
        connection.execute(text("ALTER TABLE activity_units ADD COLUMN activity_text TEXT"))
    if "activity_text_kind" not in columns:
        connection.execute(
            text(
                f"""
                ALTER TABLE activity_units
                ADD COLUMN activity_text_kind VARCHAR DEFAULT '{ACTIVITY_TEXT_KIND_UNAVAILABLE}' NOT NULL
                """,
            ),
        )
    if "activity_text_status" not in columns:
        connection.execute(
            text(
                f"""
                ALTER TABLE activity_units
                ADD COLUMN activity_text_status VARCHAR DEFAULT '{ACTIVITY_TEXT_STATUS_PENDING}' NOT NULL
                """,
            ),
        )
    if "activity_text_metadata_json" not in columns:
        connection.execute(
            text(
                """
                ALTER TABLE activity_units
                ADD COLUMN activity_text_metadata_json JSON DEFAULT '{}' NOT NULL
                """,
            ),
        )

    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_activity_units_analysis_run_text_status
            ON activity_units (analysis_run_id, activity_text_status)
            """,
        ),
    )


def _add_episode_manifest_tool_result_text_byte_count(connection: Connection) -> None:
    columns = _sqlite_table_columns(connection, "episode_manifests")
    if not columns:
        return
    if "tool_result_text_byte_count" not in columns:
        connection.execute(
            text(
                """
                ALTER TABLE episode_manifests
                ADD COLUMN tool_result_text_byte_count INTEGER DEFAULT 0 NOT NULL
                """,
            ),
        )
    if "omitted_raw_text_bytes" in columns:
        connection.execute(
            text(
                """
                UPDATE episode_manifests
                SET tool_result_text_byte_count = omitted_raw_text_bytes
                WHERE tool_result_text_byte_count = 0 OR tool_result_text_byte_count IS NULL
                """,
            ),
        )


def _create_transcript_entries_fts(connection: Connection) -> None:
    connection.execute(
        text(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS transcript_entries_fts
            USING fts5(search_text)
            """,
        ),
    )


def _add_jobs_idempotency_key(connection: Connection) -> None:
    columns = _sqlite_table_columns(connection, "jobs")
    if not columns:
        return
    if "idempotency_key" not in columns:
        connection.execute(text("ALTER TABLE jobs ADD COLUMN idempotency_key VARCHAR"))

    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_idempotency_key
            ON jobs (idempotency_key)
            """,
        ),
    )


def _add_durable_memory_claim_identity(connection: Connection) -> None:
    if not _sqlite_table_exists(connection, "durable_memory_items"):
        return

    connection.execute(
        text(
            """
            DELETE FROM durable_memory_items
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM durable_memory_items
                GROUP BY quality_report_id, claim_index
            )
            """,
        ),
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_durable_memory_items_quality_claim
            ON durable_memory_items (quality_report_id, claim_index)
            """,
        ),
    )


def _sqlite_table_columns(connection: Connection, table_name: str) -> set[str]:
    if not _sqlite_table_exists(connection, table_name):
        return set()
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table_name})"))}


def _sqlite_table_exists(connection: Connection, table_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = :table_name
                """,
            ),
            {"table_name": table_name},
        ).scalar_one_or_none()
        is not None
    )


SQLITE_MIGRATIONS = (
    SQLiteMigration(1, _add_transcript_lineage),
    SQLiteMigration(2, _add_activity_source_origin),
    SQLiteMigration(3, _add_activity_text),
    SQLiteMigration(4, _add_episode_manifest_tool_result_text_byte_count),
    SQLiteMigration(5, _create_transcript_entries_fts),
    SQLiteMigration(6, _add_jobs_idempotency_key),
    SQLiteMigration(7, _add_durable_memory_claim_identity),
)
