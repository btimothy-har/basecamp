"""Tests for the companion analysis model (daemon-sourced, no sidecar IO)."""

from __future__ import annotations

from basecamp.companion.analysis import MAX_SECTION_ITEMS, CompanionAnalysis


class TestSectionCap:
    """Section item-count cap behavior."""

    def test_construction_truncates_over_cap(self) -> None:
        over_cap = [f"item {index}" for index in range(MAX_SECTION_ITEMS + 3)]
        analysis = CompanionAnalysis(checkpoints=over_cap)
        assert analysis.checkpoints == over_cap[:MAX_SECTION_ITEMS]

    def test_validate_truncates_over_cap(self) -> None:
        payload = {"checkpoints": [f"line {index}" for index in range(MAX_SECTION_ITEMS + 2)]}
        analysis = CompanionAnalysis.model_validate(payload)
        assert len(analysis.checkpoints) == MAX_SECTION_ITEMS


class TestParseDaemonPayload:
    """Parsing the daemon's /analysis response (camelCase, optional metadata)."""

    def test_parses_camel_case_daemon_response(self) -> None:
        analysis = CompanionAnalysis.model_validate(
            {
                "monitor": ["m"],
                "needsCapture": ["n"],
                "checkpoints": ["c"],
                "sessionId": "session-123",
                "model": "prov/model",
                "updatedAt": "2026-06-04T12:34:56Z",
            }
        )
        assert analysis.monitor == ["m"]
        assert analysis.needs_capture == ["n"]
        assert analysis.checkpoints == ["c"]
        assert analysis.session_id == "session-123"
        assert analysis.model == "prov/model"
        assert analysis.updated_at == "2026-06-04T12:34:56Z"

    def test_defaults_when_sections_and_metadata_absent(self) -> None:
        analysis = CompanionAnalysis.model_validate({"model": "x"})
        assert analysis.monitor == []
        assert analysis.needs_capture == []
        assert analysis.checkpoints == []
        assert analysis.session_id is None
        assert analysis.updated_at is None

    def test_ignores_unknown_fields(self) -> None:
        analysis = CompanionAnalysis.model_validate({"monitor": ["m"], "basedOnThreadSeq": 7, "version": 2})
        assert analysis.monitor == ["m"]
