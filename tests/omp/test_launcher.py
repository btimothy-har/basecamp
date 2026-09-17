"""Tests for the project-aware ``bomp`` launch plan and process handoff."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest

from basecamp.core.exceptions import LauncherError
from basecamp.core.models import ProjectConfig
from basecamp.omp import launcher
from basecamp.omp.detached_plan import DetachedPlan, GitSource
from basecamp.omp.detached_run import CleanupFailure, DetachedWorkspace
from basecamp.omp.launch_arguments import DetachedArguments
from basecamp.omp.launch_plan import LaunchPlan


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "initial",
        ],
        check=True,
    )


def _make_extension(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "package.json").write_text("{}")
    (path / "extension.ts").write_text("export default () => {}")
    return path


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--cwd", "repo/nested", "prompt"], "repo/nested"),
        (["--cwd=repo/nested", "prompt"], "repo/nested"),
        (["--cwd=first", "--cwd", "second"], "second"),
        (["--append-system-prompt", "--cwd", "repo/nested"], "."),
        (["--plan", "--cwd", "repo/nested"], "."),
        (["--cwd=repo/nested", "--cwd="], "."),
        (["--cwd=first", "--cwd"], "first"),
        (["--cwd=~/literal"], "~/literal"),
        (["--", "--cwd=ignored"], "."),
    ],
)
def test_effective_cwd_observes_omp_syntax_without_consuming_args(
    tmp_path: Path,
    args: list[str],
    expected: str,
) -> None:
    assert launcher.effective_cwd(tmp_path, args) == (tmp_path / expected).resolve()


def test_effective_cwd_mirrors_omp_home_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    fallback = home / "tmp"
    fallback.mkdir(parents=True)

    assert launcher.effective_cwd(home, [], home=home) == fallback.resolve()
    assert launcher.effective_cwd(home, ["--cwd="], home=home) == fallback.resolve()
    assert launcher.effective_cwd(home, ["--allow-home"], home=home) == home.resolve()
    assert launcher.effective_cwd(home, ["--cwd", str(home)], home=home) == home.resolve()


def test_build_launch_matches_subdirectory_and_preserves_all_user_args(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = home / "projects" / "demo"
    nested = repo / "nested"
    shared = home / "projects" / "shared"
    explicit = tmp_path / "explicit"
    _init_repo(repo)
    nested.mkdir()
    shared.mkdir()
    user_args = [
        "--cwd",
        str(nested),
        f"--add-dir={explicit}",
        "--model",
        "test-model",
        "unchanged prompt",
    ]
    project = ProjectConfig(
        repo_root="projects/demo",
        additional_dirs=["projects/shared"],
        context="legacy-context",
        working_style="legacy-style",
    )

    plan = launcher.build_launch(
        tmp_path,
        user_args,
        {"demo": project},
        tmp_path / "basecamp" / "omp",
        home=home,
    )

    assert plan.project_name == "demo"
    assert plan.warnings == ()
    assert plan.argv == [
        "omp",
        "--extension",
        str((tmp_path / "basecamp" / "omp").resolve()),
        f"--add-dir={shared.resolve()}",
        *user_args,
    ]


def test_build_launch_matches_linked_worktree_to_primary_checkout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = home / "projects" / "demo"
    worktree = tmp_path / "worktree"
    shared = home / "projects" / "shared"
    _init_repo(repo)
    shared.mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(worktree)],
        check=True,
    )

    plan = launcher.build_launch(
        worktree,
        [],
        {"demo": ProjectConfig(repo_root="projects/demo", additional_dirs=["projects/shared"])},
        tmp_path / "omp",
        home=home,
    )

    assert plan.project_name == "demo"
    assert f"--add-dir={shared.resolve()}" in plan.argv


def test_build_launch_without_matching_repository_only_loads_extension(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    user_args = ["--mode=rpc", "--no-session"]

    plan = launcher.build_launch(
        plain,
        user_args,
        {"demo": ProjectConfig(repo_root="projects/demo")},
        tmp_path / "omp",
        home=tmp_path,
    )

    assert plan.project_name is None
    assert plan.warnings == ()
    assert plan.argv == ["omp", "--extension", str((tmp_path / "omp").resolve()), *user_args]


def test_build_launch_omits_roots_for_ambiguous_project(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shared = tmp_path / "shared"
    _init_repo(repo)
    shared.mkdir()
    projects = {
        "alpha": ProjectConfig(repo_root=str(repo), additional_dirs=[str(shared)]),
        "beta": ProjectConfig(repo_root=str(repo), additional_dirs=[str(shared)]),
    }

    plan = launcher.build_launch(repo, [], projects, tmp_path / "omp", home=tmp_path)

    assert plan.project_name is None
    assert not any(argument.startswith("--add-dir=") for argument in plan.argv)
    assert plan.warnings == (
        f"Multiple Basecamp projects match {repo.resolve()}: alpha, beta; "
        "starting without inferred project directories.",
    )


def test_build_launch_warns_and_skips_unavailable_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    available = tmp_path / "available"
    unreadable = tmp_path / "unreadable"
    missing = tmp_path / "missing"
    _init_repo(repo)
    available.mkdir()
    unreadable.mkdir()
    original_access = launcher.os.access
    monkeypatch.setattr(
        launcher.os,
        "access",
        lambda path, mode: False if path == unreadable else original_access(path, mode),
    )

    plan = launcher.build_launch(
        repo,
        [],
        {
            "demo": ProjectConfig(
                repo_root=str(repo),
                additional_dirs=[str(available), str(unreadable), str(missing)],
            )
        },
        tmp_path / "omp",
        home=tmp_path,
    )

    assert f"--add-dir={available.resolve()}" in plan.argv
    assert f"--add-dir={unreadable.resolve()}" not in plan.argv
    assert f"--add-dir={missing.resolve()}" not in plan.argv
    assert plan.warnings == (
        f"Skipping unavailable Basecamp project directory: {unreadable.resolve()}",
        f"Skipping unavailable Basecamp project directory: {missing.resolve()}",
    )


def test_build_launch_skips_directory_that_cannot_be_resolved(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    cyclic = tmp_path / "cyclic"
    available = tmp_path / "available"
    _init_repo(repo)
    cyclic.symlink_to(cyclic)
    available.mkdir()

    plan = launcher.build_launch(
        repo,
        [],
        {
            "demo": ProjectConfig(
                repo_root=str(repo),
                additional_dirs=[str(cyclic), str(available)],
            )
        },
        tmp_path / "omp",
        home=tmp_path,
    )

    assert plan.warnings == (f"Skipping unavailable Basecamp project directory: {cyclic}",)
    assert f"--add-dir={available.resolve()}" in plan.argv


def test_resolve_extension_dir_prefers_editable_source_checkout(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    module_file = source_root / "src" / "basecamp" / "omp" / "launcher.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()
    source_package = _make_extension(source_root / "omp")

    result = launcher.resolve_extension_dir(
        install_dir=str(tmp_path / "installed"),
        module_file=module_file,
    )

    assert result == source_package


def test_resolve_extension_dir_uses_installer_metadata_outside_source(tmp_path: Path) -> None:
    module_file = tmp_path / "venv" / "src" / "basecamp" / "omp" / "launcher.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()
    install_root = tmp_path / "installed"

    assert (
        launcher.resolve_extension_dir(
            install_dir=str(install_root),
            module_file=module_file,
        )
        == install_root / "omp"
    )


def test_run_launch_warns_then_replaces_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    missing = tmp_path / "missing"
    extension = _make_extension(tmp_path / "basecamp" / "omp")
    _init_repo(repo)
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/bin/omp")
    captured: dict[str, object] = {}

    def fake_execvpe(file: str, args: list[str], _environment: dict[str, str]) -> None:
        captured["file"] = file
        captured["args"] = args

    monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)

    launcher.run_launch(
        ["--help"],
        cwd=repo,
        projects={"demo": ProjectConfig(repo_root=str(repo), additional_dirs=[str(missing)])},
        extension_dir=extension,
    )

    assert captured == {
        "file": "omp",
        "args": ["omp", "--extension", str(extension.resolve()), "--help"],
    }
    assert capsys.readouterr().err == (
        f"bomp: warning: Skipping unavailable Basecamp project directory: {missing.resolve()}\n"
    )


def test_run_launch_rejects_missing_omp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: None)

    with pytest.raises(LauncherError, match="OMP executable not found"):
        launcher.run_launch([])


def test_run_launch_rejects_missing_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/bin/omp")

    with pytest.raises(LauncherError, match="Basecamp OMP extension not found"):
        launcher.run_launch([], extension_dir=tmp_path / "missing")


def test_run_launch_wraps_exec_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extension = _make_extension(tmp_path / "omp")
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/bin/omp")
    monkeypatch.setattr(
        launcher.os,
        "execvpe",
        lambda _file, _args, _environment: (_ for _ in ()).throw(OSError("exec failed")),
    )

    with pytest.raises(LauncherError, match="Could not start OMP: exec failed"):
        launcher.run_launch([], cwd=tmp_path, projects={}, extension_dir=extension)


def test_run_launch_supervises_and_cleans_detached_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    extension = _make_extension(tmp_path / "omp")
    source = tmp_path / "source"
    workspace_path = tmp_path / "worktrees" / "detached"
    workspace = DetachedWorkspace(path=workspace_path, launch_cwd=workspace_path / "nested", warnings=())
    detached = DetachedPlan(
        arguments=DetachedArguments(
            source_cwd=source / "nested",
            omp_args=("--mode=rpc", "unchanged prompt"),
            profile=None,
        ),
        source=GitSource(root=source, relative_cwd=Path("nested"), head="abc1234"),
        worktree_base=tmp_path / "worktrees",
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/tools/omp")
    monkeypatch.setattr(launcher, "plan_detached_launch", lambda *_args, **_kwargs: detached)
    monkeypatch.setattr(launcher, "create_workspace", lambda *_args, **_kwargs: workspace)

    def fake_build_launch(
        cwd: Path,
        args: list[str] | tuple[str, ...],
        projects: dict[str, ProjectConfig],
        package: Path,
    ) -> LaunchPlan:
        captured.update(cwd=cwd, args=args, projects=projects, package=package)
        return LaunchPlan(argv=["omp", "--extension", str(package), *args], project_name=None, warnings=())

    def fake_supervise(argv: list[str], **kwargs: object) -> int:
        captured["argv"] = argv
        captured.update(kwargs)
        return 37

    monkeypatch.setattr(launcher, "build_launch", fake_build_launch)
    monkeypatch.setattr(launcher, "supervise_omp", fake_supervise)
    monkeypatch.setattr(
        launcher,
        "remove_workspace",
        lambda source_root, path: captured.update(cleanup=(source_root, path)),
    )

    status = launcher.run_launch(
        ["--detached", "--cwd", str(source / "nested"), "--mode=rpc", "unchanged prompt"],
        cwd=tmp_path,
        projects={},
        extension_dir=extension,
        environ={"HOME": str(tmp_path), "GIT_DIR": str(tmp_path / "redirected-git-dir")},
    )

    assert status == 37
    assert captured["cwd"] == workspace.launch_cwd
    assert captured["args"] == ("--mode=rpc", "unchanged prompt")
    assert captured["argv"] == ["omp", "--extension", str(extension), "--mode=rpc", "unchanged prompt"]
    assert captured["cleanup"] == (source, workspace_path)
    assert "GIT_DIR" not in captured["environ"]
    assert "use /wt <branch> before exit to retain code" in capsys.readouterr().err


def test_run_launch_reports_cleanup_failure_without_overriding_child_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    extension = _make_extension(tmp_path / "omp")
    source = tmp_path / "source"
    workspace_path = tmp_path / "worktree"
    detached = DetachedPlan(
        arguments=DetachedArguments(source_cwd=source, omp_args=(), profile=None),
        source=GitSource(root=source, relative_cwd=Path("."), head="abc1234"),
        worktree_base=tmp_path,
    )
    workspace = DetachedWorkspace(path=workspace_path, launch_cwd=workspace_path, warnings=())
    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/tools/omp")
    monkeypatch.setattr(launcher, "plan_detached_launch", lambda *_args, **_kwargs: detached)
    monkeypatch.setattr(launcher, "create_workspace", lambda *_args, **_kwargs: workspace)
    monkeypatch.setattr(
        launcher,
        "build_launch",
        lambda *_args, **_kwargs: LaunchPlan(argv=["omp"], project_name=None, warnings=()),
    )
    monkeypatch.setattr(launcher, "supervise_omp", lambda *_args, **_kwargs: 19)
    monkeypatch.setattr(
        launcher,
        "remove_workspace",
        lambda *_args: CleanupFailure(detail="locked", recovery_command="git targeted cleanup"),
    )

    status = launcher.run_launch(
        ["--detached"],
        cwd=tmp_path,
        projects={},
        extension_dir=extension,
        environ={},
    )

    assert status == 19
    assert "could not remove detached worktree" in capsys.readouterr().err


def test_run_launch_defers_termination_until_owned_workspace_is_cleaned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    extension = _make_extension(tmp_path / "omp")
    source = tmp_path / "source"
    workspace_path = tmp_path / "worktree"
    detached = DetachedPlan(
        arguments=DetachedArguments(source_cwd=source, omp_args=(), profile=None),
        source=GitSource(root=source, relative_cwd=Path("."), head="abc1234"),
        worktree_base=tmp_path,
    )
    workspace = DetachedWorkspace(path=workspace_path, launch_cwd=workspace_path, warnings=())
    cleaned: list[tuple[Path, Path]] = []

    def create_then_terminate(*_args: object, **_kwargs: object) -> DetachedWorkspace:
        launcher.os.kill(launcher.os.getpid(), signal.SIGTERM)
        return workspace

    monkeypatch.setattr(launcher.shutil, "which", lambda _command: "/tools/omp")
    monkeypatch.setattr(launcher, "plan_detached_launch", lambda *_args, **_kwargs: detached)
    monkeypatch.setattr(launcher, "create_workspace", create_then_terminate)
    monkeypatch.setattr(launcher, "remove_workspace", lambda root, path: cleaned.append((root, path)))
    monkeypatch.setattr(
        launcher,
        "supervise_omp",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("child must not start")),
    )

    status = launcher.run_launch(
        ["--detached"],
        cwd=tmp_path,
        projects={},
        extension_dir=extension,
        environ={},
    )

    assert status == 128 + signal.SIGTERM
    assert cleaned == [(source, workspace_path)]
