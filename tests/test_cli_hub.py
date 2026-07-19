from click.testing import CliRunner

import basecamp.cli as cli
import basecamp.hub.claude.server as claude_server


def test_hub_boots_the_claude_daemon_by_default(monkeypatch) -> None:
    calls: list[tuple[str, str | None, str | None]] = []
    monkeypatch.setattr(
        claude_server,
        "run_claude_hub",
        lambda uds, db, pidfile: calls.append((uds, db, pidfile)),
    )

    result = CliRunner().invoke(
        cli.basecamp,
        [
            "hub",
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
