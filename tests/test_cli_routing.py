from click.testing import CliRunner

import basecamp.cli as cli
import basecamp.config_cli.config_porcelain as porcelain
from basecamp.config_cli.config_group import config


def test_top_level_commands_match_new_shape() -> None:
    commands = cli.basecamp.commands

    assert "config" in commands
    assert "companion" in commands
    assert "setup" in commands
    assert "install" in commands
    assert "hub" in commands
    # projects/environments moved under `config` (hard cut).
    assert "projects" not in commands
    assert "environments" not in commands


def test_config_subcommands_match_new_shape() -> None:
    commands = config.commands

    for name in ("project", "env", "alias", "show", "get", "set", "unset", "edit"):
        assert name in commands, name


def test_companion_subcommands_match_new_shape() -> None:
    assert "dashboard" in cli.companion.commands
    assert "analyze" not in cli.companion.commands  # analysis runs in the daemon


def test_config_env_subcommands_delegate(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(porcelain, "execute_environment_list", lambda: calls.append(("list",)))
    monkeypatch.setattr(porcelain, "set_environment", lambda repo, env: calls.append(("set", repo, env.setup)))
    monkeypatch.setattr(porcelain, "remove_environment", lambda repo: calls.append(("remove", repo)))

    runner = CliRunner()
    assert runner.invoke(config, ["env", "list"]).exit_code == 0
    assert runner.invoke(config, ["env", "set", "org/name", "uv sync"]).exit_code == 0
    assert runner.invoke(config, ["env", "remove", "org/name"]).exit_code == 0

    assert calls == [("list",), ("set", "org/name", "uv sync"), ("remove", "org/name")]


def test_config_project_subcommands_delegate(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(porcelain, "execute_project_list", lambda: calls.append(("list",)))
    monkeypatch.setattr(porcelain, "execute_project_add", lambda: calls.append(("add",)))
    monkeypatch.setattr(porcelain, "execute_project_edit", lambda name: calls.append(("edit", name)))
    monkeypatch.setattr(porcelain, "execute_project_remove", lambda name: calls.append(("remove", name)))

    runner = CliRunner()
    assert runner.invoke(config, ["project", "list"]).exit_code == 0
    assert runner.invoke(config, ["project", "add"]).exit_code == 0
    assert runner.invoke(config, ["project", "edit", "demo"]).exit_code == 0
    assert runner.invoke(config, ["project", "remove", "demo"]).exit_code == 0

    assert calls == [("list",), ("add",), ("edit", "demo"), ("remove", "demo")]


def test_bare_config_sections_open_menus(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(porcelain, "run_project_menu", lambda *_a, **_k: calls.append("project"))
    monkeypatch.setattr(porcelain, "run_environments_menu", lambda *_a, **_k: calls.append("env"))

    runner = CliRunner()
    assert runner.invoke(config, ["project"]).exit_code == 0
    assert runner.invoke(config, ["env"]).exit_code == 0
    assert calls == ["project", "env"]


def test_companion_dashboard_delegates(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None]] = []
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


def test_old_top_level_routes_are_absent() -> None:
    runner = CliRunner()
    for argv in (["projects"], ["environments"]):
        result = runner.invoke(cli.basecamp, argv)
        assert result.exit_code != 0
        assert "No such command" in result.output
