"""Tests for core.cli.log — basecamp log command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from core.cli.log import execute_log
from core.exceptions import LogseqNotConfiguredError


class TestExecuteLog:
    """Integration tests for the log command."""

    def test_appends_to_journal(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with patch("core.cli.log.resolve_graph_path", return_value=graph):
            execute_log("first thought")

        journal_files = list((graph / "journals").iterdir())
        assert len(journal_files) == 1
        assert journal_files[0].read_text() == "- first thought\n"

    def test_appends_with_project(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with patch("core.cli.log.resolve_graph_path", return_value=graph):
            execute_log("shipped it", project="Basecamp")

        journal_files = list((graph / "journals").iterdir())
        assert journal_files[0].read_text() == "- [[Basecamp]] shipped it\n"

    def test_multiple_entries_append(self, tmp_path: Path) -> None:
        graph = tmp_path / "brain"
        graph.mkdir()

        with patch("core.cli.log.resolve_graph_path", return_value=graph):
            execute_log("first")
            execute_log("second")

        journal_files = list((graph / "journals").iterdir())
        assert journal_files[0].read_text() == "- first\n- second\n"

    def test_not_configured_raises(self) -> None:
        with patch("core.cli.log.resolve_graph_path", side_effect=LogseqNotConfiguredError):
            with pytest.raises(LogseqNotConfiguredError):
                execute_log("should fail")
