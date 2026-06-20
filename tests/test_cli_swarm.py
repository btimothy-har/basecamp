from pathlib import Path

from click.testing import CliRunner

import basecamp.cli as cli


def test_swarm_daemon_runs_pi_swarm_daemon(monkeypatch) -> None:
    calls: list[tuple[str, str | None, str | None]] = []

    monkeypatch.setattr(cli, "HAS_SWARM", True)
    monkeypatch.setattr(
        cli,
        "run_swarm_daemon",
        lambda uds, db, pidfile: calls.append((uds, db, pidfile)),
    )

    result = CliRunner().invoke(
        cli.basecamp,
        [
            "swarm",
            "daemon",
            "--uds",
            "/tmp/basecamp.sock",
            "--db",
            "/tmp/basecamp.db",
            "--pidfile",
            "/tmp/basecamp.pid",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("/tmp/basecamp.sock", "/tmp/basecamp.db", "/tmp/basecamp.pid")]


def test_swarm_daemon_reports_missing_runtime(monkeypatch) -> None:
    monkeypatch.setattr(cli, "HAS_SWARM", False)
    monkeypatch.setattr(cli, "run_swarm_daemon", None)

    result = CliRunner().invoke(
        cli.basecamp,
        ["swarm", "daemon", "--uds", str(Path("/tmp/basecamp.sock"))],
    )

    assert result.exit_code == 1
    assert "swarm is not installed. Run: basecamp install" in result.output
