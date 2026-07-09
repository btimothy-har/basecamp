from click.testing import CliRunner

import basecamp.cli as cli


def test_swarm_daemon_runs_basecamp_swarm_daemon(monkeypatch) -> None:
    calls: list[tuple[str, str | None, str | None]] = []

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
