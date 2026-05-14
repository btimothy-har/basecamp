import json
from typing import Any

import pi_memory.cli.main as cli_module
from click.testing import CliRunner
from pi_memory import __version__

CONNECTION_REFUSED = "connection refused"


def test_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_resolves() -> None:
    result = CliRunner().invoke(cli_module.main, ["--help"])

    assert result.exit_code == 0
    assert "Pi memory service." in result.output


def test_serve_help_resolves() -> None:
    result = CliRunner().invoke(cli_module.main, ["serve", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output


def test_status_help_resolves() -> None:
    result = CliRunner().invoke(cli_module.main, ["status", "--help"])

    assert result.exit_code == 0
    assert "--host" in result.output
    assert "--port" in result.output
    assert "--timeout" in result.output
    assert "--json" in result.output


def test_status_reports_healthy_service(monkeypatch) -> None:
    def fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
        assert url == "http://127.0.0.2:9876/v1/status"
        assert timeout == 0.25
        return {
            "service_name": "pi-memory",
            "version": "0.1.0",
            "pid": 123,
            "uptime_seconds": 4.5,
            "memory_dir": "/tmp/pi-memory",
        }

    monkeypatch.setattr(cli_module, "_fetch_status", fetch_status)

    result = CliRunner().invoke(
        cli_module.main,
        ["status", "--host", "127.0.0.2", "--port", "9876", "--timeout", "0.25"],
    )

    assert result.exit_code == 0
    assert "pi-memory is healthy at http://127.0.0.2:9876/v1/status" in result.output
    assert "version: 0.1.0" in result.output
    assert "pid: 123" in result.output
    assert "uptime_seconds: 4.5" in result.output
    assert "memory_dir: /tmp/pi-memory" in result.output


def test_status_reports_unavailable_service(monkeypatch) -> None:
    error = cli_module.StatusProbeError.unavailable(CONNECTION_REFUSED)

    def fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
        assert url == "http://127.0.0.1:8765/v1/status"
        assert timeout == 1.0
        raise error

    monkeypatch.setattr(cli_module, "_fetch_status", fetch_status)

    result = CliRunner().invoke(cli_module.main, ["status"])

    assert result.exit_code == 1
    assert "pi-memory is unavailable at http://127.0.0.1:8765/v1/status: connection refused" in result.output


def test_status_json_reports_healthy_service(monkeypatch) -> None:
    service_status = {
        "service_name": "pi-memory",
        "version": "0.1.0",
        "pid": 123,
        "uptime_seconds": 4.5,
        "memory_dir": "/tmp/pi-memory",
    }

    def fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
        assert url == "http://127.0.0.1:8765/v1/status"
        assert timeout == 1.0
        return service_status

    monkeypatch.setattr(cli_module, "_fetch_status", fetch_status)

    result = CliRunner().invoke(cli_module.main, ["status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "ok": True,
        "url": "http://127.0.0.1:8765/v1/status",
        "status": service_status,
    }


def test_status_json_reports_unavailable_service(monkeypatch) -> None:
    error = cli_module.StatusProbeError.unavailable(CONNECTION_REFUSED)

    def fetch_status(*, url: str, timeout: float) -> dict[str, Any]:
        assert url == "http://127.0.0.1:8765/v1/status"
        assert timeout == 1.0
        raise error

    monkeypatch.setattr(cli_module, "_fetch_status", fetch_status)

    result = CliRunner().invoke(cli_module.main, ["status", "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data == {
        "ok": False,
        "url": "http://127.0.0.1:8765/v1/status",
        "error": "connection refused",
    }
