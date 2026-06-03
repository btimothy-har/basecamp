"""Tests for companion analysis model and sidecar helpers."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.companion.analysis import (
    COMPANION_ANALYSIS_VERSION,
    CompanionAnalysis,
    companion_analysis_path,
    load_analysis,
    write_analysis,
)


class TestWriteAndLoadAnalysis:
    """Analysis read/write behavior."""

    def test_round_trip_write_then_load(self, tmp_path: Path) -> None:
        path = tmp_path / "analysis.json"
        analysis = CompanionAnalysis(
            version=COMPANION_ANALYSIS_VERSION,
            session_id="session-123",
            updated_at="2026-06-04T12:34:56Z",
            model="gpt-5.3",
            recap=["Recap line"],
            decisions=["Decision line"],
            todos=["Todo line"],
            deferred=["Deferred line"],
            warnings=["Warning line"],
        )

        write_analysis(path, analysis)
        loaded = load_analysis(path)

        assert loaded is not None
        assert loaded == analysis

    def test_written_json_uses_camel_case_and_load_accepts_it(self, tmp_path: Path) -> None:
        path = tmp_path / "analysis.json"
        analysis = CompanionAnalysis(
            version=COMPANION_ANALYSIS_VERSION,
            session_id="session-456",
            updated_at="2026-06-04T12:34:56Z",
        )

        write_analysis(path, analysis)

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "sessionId" in payload
        assert "updatedAt" in payload
        assert "session_id" not in payload
        assert "updated_at" not in payload

        loaded = load_analysis(path)
        assert loaded is not None
        assert loaded.session_id == "session-456"
        assert loaded.updated_at == "2026-06-04T12:34:56Z"


class TestLoadAnalysis:
    """Analysis loading failure behavior."""

    def test_load_analysis_missing_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.analysis.json"
        assert load_analysis(path) is None

    def test_load_analysis_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.analysis.json"
        path.write_text("{invalid", encoding="utf-8")

        assert load_analysis(path) is None

    def test_load_analysis_validation_failure_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad-schema.analysis.json"
        path.write_text(
            json.dumps(
                {
                    "sessionId": "session-123",
                    "updatedAt": "2026-06-04T12:34:56Z",
                }
            ),
            encoding="utf-8",
        )

        assert load_analysis(path) is None


class TestCompanionAnalysisPath:
    """Analysis path helper behavior."""

    def test_sanitizes_session_id_and_uses_analysis_suffix(self, tmp_path: Path) -> None:
        path = companion_analysis_path("a/b:c", base_dir=tmp_path)
        assert path == tmp_path / "a_b_c.analysis.json"

    def test_uses_default_companion_base_dir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("basecamp.companion.analysis.Path.home", lambda: tmp_path)

        path = companion_analysis_path("session-123")

        assert path == tmp_path / ".pi" / "companion" / "session-123.analysis.json"
