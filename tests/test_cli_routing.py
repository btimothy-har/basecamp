from click.testing import CliRunner

import basecamp.cli as cli


def test_top_level_commands_match_new_shape() -> None:
    commands = cli.basecamp.commands

    assert "projects" in commands
    assert "companion" in commands
    assert "setup" in commands
    assert "install" in commands
    assert "swarm" in commands
    assert "companion-analyze" in commands
    assert "config" not in commands


def test_companion_subcommands_match_new_shape() -> None:
    commands = cli.companion.commands

    assert "dashboard" in commands
    assert "analyze" in commands


def test_projects_subcommands_delegate(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(cli, "execute_project_list", lambda: calls.append(("list", None)))
    monkeypatch.setattr(cli, "execute_project_add", lambda: calls.append(("add", None)))
    monkeypatch.setattr(cli, "execute_project_edit", lambda name: calls.append(("edit", name)))
    monkeypatch.setattr(cli, "execute_project_remove", lambda name: calls.append(("remove", name)))

    runner = CliRunner()

    result = runner.invoke(cli.basecamp, ["projects", "list"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli.basecamp, ["projects", "add"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli.basecamp, ["projects", "edit", "demo"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli.basecamp, ["projects", "remove", "demo"])
    assert result.exit_code == 0, result.output

    assert calls == [("list", None), ("add", None), ("edit", "demo"), ("remove", "demo")]


def test_projects_without_subcommand_opens_project_menu(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cli, "run_project_menu", lambda: calls.append("menu"))

    result = CliRunner().invoke(cli.basecamp, ["projects"])

    assert result.exit_code == 0, result.output
    assert calls == ["menu"]


def test_companion_dashboard_delegates(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(cli, "HAS_COMPANION", True)
    monkeypatch.setattr(
        cli,
        "run_companion",
        lambda snapshot, cwd, scratch: calls.append((str(snapshot), str(cwd), str(scratch) if scratch else None)),
    )

    result = CliRunner().invoke(
        cli.basecamp,
        [
            "companion",
            "dashboard",
            "--snapshot",
            "/tmp/snapshot.json",
            "--cwd",
            "/tmp/worktree",
            "--scratch",
            "/tmp/scratch",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("/tmp/snapshot.json", "/tmp/worktree", "/tmp/scratch")]


def test_deprecated_companion_analyze_alias_delegates(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(cli, "HAS_COMPANION", True)
    monkeypatch.setattr(
        cli,
        "analyze",
        lambda session_id, base_dir: calls.append((session_id, str(base_dir) if base_dir else None)),
    )

    result = CliRunner().invoke(
        cli.basecamp,
        ["companion-analyze", "--session-id", "s", "--base-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "deprecated" in result.output
    assert calls == [("s", str(tmp_path))]


def test_old_cli_routes_are_absent() -> None:
    runner = CliRunner()

    result = runner.invoke(cli.basecamp, ["config"])
    assert result.exit_code != 0
    assert "No such command" in result.output

    result = runner.invoke(cli.basecamp, ["companion", "--snapshot", "snapshot.json", "--cwd", "."])
    assert result.exit_code != 0
    assert "No such option" in result.output or "Missing command" in result.output
