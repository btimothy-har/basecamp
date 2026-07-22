"""CLI wiring for the local agents dashboard."""

from __future__ import annotations

from click.testing import CliRunner

import basecamp.cli as cli
from basecamp.core.exceptions import LauncherError
from basecamp.hub.launcher import DashboardLaunchError


def test_agents_opens_dashboard(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "open_agents_dashboard", lambda: calls.append("open"))

    result = CliRunner().invoke(cli.basecamp, ["agents"])

    assert result.exit_code == 0, result.output
    assert calls == ["open"]


def test_agents_reports_launcher_error(monkeypatch) -> None:
    errors: list[str] = []
    launch_error = DashboardLaunchError.unavailable("port occupied")

    def fail() -> None:
        raise launch_error

    def handle(error: LauncherError) -> None:
        errors.append(str(error))
        raise SystemExit(1)

    monkeypatch.setattr(cli, "open_agents_dashboard", fail)
    monkeypatch.setattr(cli, "_handle_error", handle)

    result = CliRunner().invoke(cli.basecamp, ["agents"])

    assert result.exit_code == 1
    assert errors == ["Dashboard unavailable: port occupied"]
