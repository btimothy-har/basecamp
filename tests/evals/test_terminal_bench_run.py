from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.terminal_bench import run


def options(tmp_path: Path, **overrides) -> run.LaunchOptions:
    values = {
        "tasks": ("terminal-bench/hf-model-inference",),
        "engine": "podman",
        "attempts": 1,
        "concurrency": 1,
        "model": "openai/gpt-5.6-sol",
        "thinking": "xhigh",
        "pi_version": "0.80.7",
        "models_file": tmp_path / "models.json",
        "jobs_dir": tmp_path / "jobs",
        "install_only": False,
        "dry_run": False,
        "confirmed": True,
    }
    values.update(overrides)
    return run.LaunchOptions(**values)


def test_resolve_tasks_expands_presets_and_normalizes_custom_names() -> None:
    assert run.resolve_tasks(("podman-arm64",)) == (
        "terminal-bench/hf-model-inference",
        "terminal-bench/mteb-retrieve",
        "terminal-bench/pytorch-model-recovery",
    )
    assert run.resolve_tasks(("hf-model-inference", "terminal-bench/hf-model-inference")) == (
        "terminal-bench/hf-model-inference",
    )
    assert run.resolve_tasks(()) == run.resolve_tasks(("podman-arm64",))


def test_build_harbor_command_includes_every_selected_task(tmp_path: Path) -> None:
    selected = options(
        tmp_path,
        tasks=("terminal-bench/hf-model-inference", "terminal-bench/pytorch-model-recovery"),
        attempts=2,
        concurrency=2,
        install_only=True,
    )

    command = run.build_harbor_command(selected, "abc123")

    assert command[:2] == ["harbor", "run"]
    assert command.count("--include-task-name") == 2
    assert "terminal-bench/hf-model-inference" in command
    assert "terminal-bench/pytorch-model-recovery" in command
    assert "basecamp_ref=abc123" in command
    assert f"pi_models_file={selected.models_file}" in command
    assert command[command.index("--n-attempts") + 1] == "2"
    assert command[command.index("--n-concurrent") + 1] == "2"
    assert command[-1] == "--install-only"


def test_validate_options_guards_paid_runs_and_invalid_resources(tmp_path: Path) -> None:
    models_file = tmp_path / "models.json"
    models_file.write_text("{}")

    with pytest.raises(run.EvalLaunchError, match="paid runs require --yes"):
        run.validate_options(options(tmp_path, models_file=models_file, confirmed=False))
    with pytest.raises(run.EvalLaunchError, match="concurrency cannot exceed"):
        run.validate_options(options(tmp_path, models_file=models_file, concurrency=2))
    with pytest.raises(run.EvalLaunchError, match="models file does not exist"):
        run.validate_options(options(tmp_path, models_file=tmp_path / "missing.json"))

    run.validate_options(options(tmp_path, models_file=models_file, confirmed=False, install_only=True))
    run.validate_options(options(tmp_path, models_file=models_file, confirmed=False, dry_run=True))


def test_build_environment_configures_repo_local_podman_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose = tmp_path / "docker-compose"
    compose.write_text("")
    monkeypatch.setenv("DOCKER_COMPOSE_BIN", str(compose))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(run.shutil, "which", lambda name: f"/fake/{name}")

    environment = run.build_environment(options(tmp_path, models_file=None))

    assert environment["DOCKER_COMPOSE_BIN"] == str(compose)
    assert environment["PATH"].split(":", 1)[0] == str(run._REPOSITORY_ROOT / "evals" / "terminal_bench" / "bin")
    assert environment["PYTHONPATH"].split(":", 1)[0] == str(run._REPOSITORY_ROOT)


def test_parse_options_supports_custom_selection_without_models() -> None:
    parsed = run.parse_options(
        [
            "hf-model-inference",
            "pytorch-model-recovery",
            "--no-models",
            "--attempts",
            "3",
            "--concurrency",
            "2",
            "--dry-run",
        ]
    )

    assert parsed.tasks == (
        "terminal-bench/hf-model-inference",
        "terminal-bench/pytorch-model-recovery",
    )
    assert parsed.models_file is None
    assert parsed.attempts == 3
    assert parsed.concurrency == 2
    assert parsed.dry_run is True


_CI_EXPECTED: tuple[str, ...] = (
    "terminal-bench/hf-model-inference",
    "terminal-bench/mteb-retrieve",
    "terminal-bench/pytorch-model-recovery",
    "terminal-bench/broken-python",
    "terminal-bench/fix-permissions",
    "terminal-bench/cron-broken-network",
    "terminal-bench/oom",
    "terminal-bench/git-multibranch",
    "terminal-bench/sanitize-git-repo",
    "terminal-bench/git-leak-recovery",
    "terminal-bench/pandas-etl",
    "terminal-bench/csv-to-parquet",
    "terminal-bench/train-fasttext",
    "terminal-bench/fix-code-vulnerability",
    "terminal-bench/crack-7z-hash",
    "terminal-bench/sql-injection-attack",
    "terminal-bench/solve-sudoku",
    "terminal-bench/weighted-max-sat-solver",
    "terminal-bench/countdown-game",
    "terminal-bench/nginx-request-logging",
    "terminal-bench/simple-web-scraper",
    "terminal-bench/build-cython-ext",
    "terminal-bench/conda-env-conflict-resolution",
    "terminal-bench/npm-conflict-resolution",
    "terminal-bench/fix-pandas-version",
    "terminal-bench/modernize-fortran-build",
    "terminal-bench/setup-custom-dev-env",
    "terminal-bench/configure-git-webserver",
    "terminal-bench/sqlite-db-truncate",
    "terminal-bench/kv-store-grpc",
    "terminal-bench/tmux-advanced-workflow",
)


def test_resolve_tasks_ci_preset_returns_expected_tasks_in_order() -> None:
    assert run.resolve_tasks(("ci",)) == _CI_EXPECTED


def test_all_selection_builds_command_without_task_filters(tmp_path: Path) -> None:
    assert run.resolve_tasks(("all",)) is None

    command = run.build_harbor_command(options(tmp_path, tasks=None), "abc123")

    assert "--include-task-name" not in command


def test_validate_options_skips_concurrency_check_for_full_dataset(tmp_path: Path) -> None:
    models_file = tmp_path / "models.json"
    models_file.write_text("{}")

    run.validate_options(options(tmp_path, models_file=models_file, tasks=None, concurrency=100))
