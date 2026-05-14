import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from pi_memory.constants import SERVICE_NAME, SERVICE_VERSION
from pi_memory.server import create_app


def test_health_endpoint(tmp_path) -> None:
    app = create_app(memory_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_status_endpoint_includes_service_metadata(tmp_path) -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    app = create_app(
        host="127.0.0.1",
        port=9876,
        memory_dir=tmp_path,
        started_at=started_at,
    )
    client = TestClient(app)

    response = client.get("/v1/status")

    assert response.status_code == 200
    data = response.json()
    assert data["service_name"] == SERVICE_NAME
    assert data["version"] == SERVICE_VERSION
    assert data["pid"] == os.getpid()
    assert data["started_at"] == started_at.isoformat()
    assert data["uptime_seconds"] >= 0
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 9876
    assert data["memory_dir"] == str(tmp_path)
