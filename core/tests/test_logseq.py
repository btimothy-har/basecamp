"""Tests for core.logseq — Logseq graph operations."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import PropertyMock, patch

import pytest
from core.exceptions import LogseqGraphNotFoundError, LogseqNotConfiguredError
from core.logseq import (
    append_block,
    ensure_journal_file,
    format_log_entry,
    resolve_graph_path,
    resolve_journal_path,
)


class TestResolveGraphPath:
    """Graph path resolution from settings."""

    def test_not_configured(self) -> None:
        with patch("core.logseq.settings") as mock_settings:
            type(mock_settings).logseq_graph = PropertyMock(return_value=None)
            with pytest.raises(LogseqNotConfiguredError):
                resolve_graph_path()

    def test_directory_missing(self, tmp_path: Path) -> None:
        with (
            patch("core.logseq.settings") as mock_settings,
            patch("core.logseq.Path") as mock_path,
        ):
            type(mock_settings).logseq_graph = PropertyMock(return_value="nonexistent")
            mock_path.home.return_value = tmp_path
            with pytest.raises(LogseqGraphNotFoundError):
                resolve_graph_path()

    def test_success(self, tmp_path: Path) -> None:
        graph_dir = tmp_path / "brain"
        graph_dir.mkdir()
        with (
            patch("core.logseq.settings") as mock_settings,
            patch("core.logseq.Path") as mock_path,
        ):
            type(mock_settings).logseq_graph = PropertyMock(return_value="brain")
            mock_path.home.return_value = tmp_path
            result = resolve_graph_path()
        assert result == graph_dir


class TestResolveJournalPath:
    """Journal file path generation."""

    def test_default_today(self, tmp_path: Path) -> None:
        with patch("core.logseq.datetime") as mock_dt:
            mock_dt.UTC = datetime.UTC
            mock_dt.datetime.now.return_value = datetime.datetime(2026, 3, 17, tzinfo=datetime.UTC)
            result = resolve_journal_path(tmp_path)
        assert result == tmp_path / "journals" / "2026_03_17.md"

    def test_specific_date(self, tmp_path: Path) -> None:
        date = datetime.date(2025, 1, 5)
        result = resolve_journal_path(tmp_path, date)
        assert result == tmp_path / "journals" / "2025_01_05.md"


class TestEnsureJournalFile:
    """Journal file and directory creation."""

    def test_creates_parents_and_file(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026_03_17.md"
        ensure_journal_file(journal)
        assert journal.exists()
        assert journal.read_text() == ""

    def test_noop_when_exists(self, tmp_path: Path) -> None:
        journal = tmp_path / "journals" / "2026_03_17.md"
        journal.parent.mkdir(parents=True)
        journal.write_text("- existing entry\n")
        ensure_journal_file(journal)
        assert journal.read_text() == "- existing entry\n"


class TestAppendBlock:
    """Block appending to journal files."""

    def test_append_to_empty_file(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.md"
        journal.touch()
        append_block(journal, "first entry")
        assert journal.read_text() == "- first entry\n"

    def test_append_to_existing_file(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.md"
        journal.write_text("- existing entry\n")
        append_block(journal, "second entry")
        assert journal.read_text() == "- existing entry\n- second entry\n"

    def test_append_handles_missing_trailing_newline(self, tmp_path: Path) -> None:
        journal = tmp_path / "journal.md"
        journal.write_text("- existing entry")
        append_block(journal, "second entry")
        assert journal.read_text() == "- existing entry\n- second entry\n"


class TestFormatLogEntry:
    """Log entry formatting."""

    def test_plain_message(self) -> None:
        assert format_log_entry("a thought") == "a thought"

    def test_with_project(self) -> None:
        assert format_log_entry("shipped it", project="Basecamp") == "[[Basecamp]] shipped it"
