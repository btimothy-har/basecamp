"""Daemon GET /analysis/{session_id} endpoint tests."""

from __future__ import annotations

from pathlib import Path

from app_helpers import _build_app_with_store
from fastapi.testclient import TestClient


def test_analysis_endpoint_returns_stored_sections_flattened(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    store.record_analysis(
        owner_id="s",
        based_on_thread_seq=3,
        model="prov/m",
        sections_json='{"monitor":["m1"],"needsCapture":["n1"],"checkpoints":[]}',
    )
    client = TestClient(app)

    response = client.get("/analysis/s")

    assert response.status_code == 200
    body = response.json()
    assert body["monitor"] == ["m1"]
    assert body["needsCapture"] == ["n1"]
    assert body["checkpoints"] == []
    assert body["sessionId"] == "s"
    assert body["model"] == "prov/m"
    assert body["updatedAt"]


def test_analysis_endpoint_404_when_absent(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    client = TestClient(app)

    assert client.get("/analysis/nobody").status_code == 404
