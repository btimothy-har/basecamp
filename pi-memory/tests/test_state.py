import json
import os

import pi_memory.server.state as state_module
import pytest
from pi_memory.constants import SERVICE_NAME, SERVICE_VERSION
from pi_memory.server import ServerAlreadyRunningError, ServerMetadata, ServerState


def test_registration_writes_metadata_and_cleans_up(tmp_path) -> None:
    state = ServerState(memory_dir=tmp_path)

    with state.register(host="127.0.0.1", port=9876) as metadata:
        assert state.lock_path.exists()
        assert state.metadata_path.exists()
        assert state.logs_dir.exists()
        assert metadata.service_name == SERVICE_NAME
        assert metadata.version == SERVICE_VERSION
        assert metadata.pid == os.getpid()

        data = json.loads(state.metadata_path.read_text(encoding="utf-8"))
        assert data["host"] == "127.0.0.1"
        assert data["port"] == 9876
        assert data["memory_dir"] == str(tmp_path)

    assert not state.lock_path.exists()
    assert not state.metadata_path.exists()


def test_registration_rejects_active_server(tmp_path) -> None:
    state = ServerState(memory_dir=tmp_path)

    with state.register(host="127.0.0.1", port=9876):
        duplicate_metadata = ServerMetadata.create(
            host="127.0.0.1",
            port=9876,
            memory_dir=tmp_path,
        )
        with pytest.raises(ServerAlreadyRunningError):
            state.acquire(duplicate_metadata)


def test_registration_replaces_stale_state(tmp_path, monkeypatch) -> None:
    state = ServerState(memory_dir=tmp_path)
    state.ensure_dirs()
    state.lock_path.write_text("123456", encoding="utf-8")
    state.metadata_path.write_text(
        json.dumps(
            {
                "service_name": SERVICE_NAME,
                "version": SERVICE_VERSION,
                "pid": 123456,
                "started_at": "2026-01-01T00:00:00+00:00",
                "host": "127.0.0.1",
                "port": 9876,
                "memory_dir": str(tmp_path),
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(state_module, "_pid_is_running", lambda _pid: False)

    with state.register(host="127.0.0.1", port=9877) as metadata:
        assert metadata.port == 9877
        assert state.lock_path.read_text(encoding="utf-8") == str(os.getpid())
