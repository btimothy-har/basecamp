from pathlib import Path
from unittest.mock import MagicMock

import pytest

import basecamp.installer as installer
from basecamp.core.exceptions import LauncherError


def _completed(returncode: int = 0, *, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_legacy_subpaths_cover_all_pre_consolidation_packages() -> None:
    assert installer._LEGACY_PACKAGE_SUBPATHS == (
        "core/pi",
        "pi-ui",
        "workspace/pi",
        "pi-tasks",
        "pi-git",
        "pi-bash-reviewer",
        "pi-engineering",
        "pi-browser",
        "pi-companion/pi",
        "pi-swarm/extension",
    )


def test_install_pi_extension_installs_root_and_cleans_legacy(mocker) -> None:
    mocker.patch.object(installer.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}")
    run = mocker.patch.object(installer.subprocess, "run", return_value=_completed())

    installer._install_pi_extension(installer.REPO_DIR)

    calls = run.call_args_list
    # npm install at the repo root
    assert calls[0].args[0] == ["/usr/bin/npm", "install"]
    assert calls[0].kwargs["cwd"] == installer.REPO_DIR
    # legacy per-package registrations removed before registering the repo root
    uninstall_targets = [call.args[0][2] for call in calls[1:-1]]
    assert uninstall_targets == [str(installer.REPO_DIR / subpath) for subpath in installer._LEGACY_PACKAGE_SUBPATHS]
    assert all(call.args[0][:2] == ["/usr/bin/pi", "uninstall"] for call in calls[1:-1])
    # single registration of the repo root as the extension
    assert calls[-1].args[0] == ["/usr/bin/pi", "install", str(installer.REPO_DIR)]


def test_legacy_uninstall_failures_are_nonfatal(mocker) -> None:
    run = mocker.patch.object(installer.subprocess, "run", return_value=_completed(returncode=1))

    installer._uninstall_legacy_pi_packages("/usr/bin/pi", installer.REPO_DIR)

    assert run.call_count == len(installer._LEGACY_PACKAGE_SUBPATHS)


def test_repo_dir_is_the_pi_extension_root() -> None:
    # The repo root carries the package manifest the installer registers; the
    # extension entry point itself lives under pi/.
    assert (Path(installer.REPO_DIR) / "pi" / "extension.ts").exists()
    assert (Path(installer.REPO_DIR) / "package.json").exists()


def test_resolve_install_root_prefers_explicit_checkout(tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")

    assert installer.resolve_install_root(checkout) == checkout.resolve()


def test_resolve_install_root_uses_recorded_checkout_for_installed_tool(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    mocker.patch.object(installer, "REPO_DIR", tmp_path / "tool-environment")
    fake_settings = MagicMock(install_dir=str(checkout))
    mocker.patch.object(installer, "settings", fake_settings)

    assert installer.resolve_install_root() == checkout.resolve()


def test_resolve_install_root_rejects_incomplete_checkout(tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    (checkout / "pi" / "extension.ts").unlink()

    with pytest.raises(LauncherError, match="source checkout not found"):
        installer.resolve_install_root(checkout)


def test_resolve_install_root_rejects_missing_checkout(mocker, tmp_path: Path) -> None:
    mocker.patch.object(installer, "REPO_DIR", tmp_path / "tool-environment")
    fake_settings = MagicMock(install_dir=str(tmp_path / "missing"))
    mocker.patch.object(installer, "settings", fake_settings)

    with pytest.raises(LauncherError, match="source checkout not found"):
        installer.resolve_install_root()


def test_ensure_omp_preserves_runnable_existing_install(mocker) -> None:
    which = mocker.patch.object(installer.shutil, "which", return_value="/usr/bin/omp")
    run = mocker.patch.object(
        installer.subprocess,
        "run",
        return_value=_completed(stdout="omp/18.1.21\n"),
    )

    installer._ensure_omp()

    which.assert_called_once_with("omp")
    run.assert_called_once_with(
        ["/usr/bin/omp", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_ensure_omp_rejects_broken_existing_install_without_overwriting(mocker) -> None:
    which = mocker.patch.object(installer.shutil, "which", return_value="/usr/bin/omp")
    run = mocker.patch.object(
        installer.subprocess,
        "run",
        return_value=_completed(returncode=1, stderr="cannot start"),
    )

    with pytest.raises(SystemExit):
        installer._ensure_omp()

    which.assert_called_once_with("omp")
    run.assert_called_once()


def test_ensure_omp_installs_missing_runtime_with_bun(mocker) -> None:
    paths = iter((None, "/usr/bin/bun", "/home/test/.bun/bin/omp"))
    which = mocker.patch.object(installer.shutil, "which", side_effect=lambda _name: next(paths))
    run = mocker.patch.object(
        installer.subprocess,
        "run",
        side_effect=(
            _completed(),
            _completed(stdout="omp/18.1.21\n"),
        ),
    )

    installer._ensure_omp()

    assert [call.args[0] for call in run.call_args_list] == [
        ["/usr/bin/bun", "install", "-g", installer.OMP_PACKAGE],
        ["/home/test/.bun/bin/omp", "--version"],
    ]
    assert [call.args[0] for call in which.call_args_list] == ["omp", "bun", "omp"]


def test_ensure_omp_requires_installed_binary_on_path(mocker) -> None:
    paths = iter((None, "/usr/bin/bun", None))
    mocker.patch.object(installer.shutil, "which", side_effect=lambda _name: next(paths))
    run = mocker.patch.object(installer.subprocess, "run", return_value=_completed())

    with pytest.raises(SystemExit):
        installer._ensure_omp()

    run.assert_called_once_with(
        ["/usr/bin/bun", "install", "-g", installer.OMP_PACKAGE],
        check=False,
        capture_output=True,
        text=True,
    )


def test_ensure_omp_requires_bun_when_omp_is_missing(mocker) -> None:
    mocker.patch.object(installer.shutil, "which", return_value=None)
    run = mocker.patch.object(installer.subprocess, "run")

    with pytest.raises(SystemExit):
        installer._ensure_omp()

    run.assert_not_called()


def test_ensure_omp_reports_global_install_failure(mocker) -> None:
    paths = iter((None, "/usr/bin/bun"))
    mocker.patch.object(installer.shutil, "which", side_effect=lambda _name: next(paths))
    run = mocker.patch.object(
        installer.subprocess,
        "run",
        return_value=_completed(returncode=1, stderr="install failed"),
    )

    with pytest.raises(SystemExit):
        installer._ensure_omp()

    run.assert_called_once_with(
        ["/usr/bin/bun", "install", "-g", installer.OMP_PACKAGE],
        check=False,
        capture_output=True,
        text=True,
    )


def test_install_records_source_only_after_every_component_succeeds(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    events: list[object] = []
    mocker.patch.object(installer.subprocess, "run", return_value=_completed())
    mocker.patch.object(installer, "_ensure_omp", side_effect=lambda: events.append("omp"))
    mocker.patch.object(installer, "_install_pi_extension", side_effect=lambda root: events.append(("pi", root)))
    fake_settings = MagicMock()
    fake_settings.set_install_metadata.side_effect = lambda **values: events.append(("metadata", values))
    mocker.patch.object(installer, "settings", fake_settings)

    installer.run_interactive_install(repo_dir=checkout)

    assert installer.subprocess.run.call_args_list[0].args[0] == [
        "uv",
        "tool",
        "install",
        "--force",
        "--reinstall",
        str(checkout.resolve()),
    ]
    assert events == [
        "omp",
        ("pi", checkout.resolve()),
        ("metadata", {"install_dir": str(checkout.resolve())}),
    ]
    fake_settings.set_install_metadata.assert_called_once()


def test_install_does_not_record_metadata_after_omp_failure(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    mocker.patch.object(installer.subprocess, "run", return_value=_completed())
    mocker.patch.object(installer, "_ensure_omp", side_effect=SystemExit(1))
    pi_install = mocker.patch.object(installer, "_install_pi_extension")
    fake_settings = MagicMock()
    mocker.patch.object(installer, "settings", fake_settings)

    with pytest.raises(SystemExit):
        installer.run_interactive_install(repo_dir=checkout)

    pi_install.assert_not_called()
    fake_settings.set_install_metadata.assert_not_called()


def test_install_does_not_record_metadata_after_pi_failure(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    mocker.patch.object(installer.subprocess, "run", return_value=_completed())
    mocker.patch.object(installer, "_ensure_omp")
    mocker.patch.object(installer, "_install_pi_extension", side_effect=SystemExit(1))
    fake_settings = MagicMock()
    mocker.patch.object(installer, "settings", fake_settings)

    with pytest.raises(SystemExit):
        installer.run_interactive_install(repo_dir=checkout)

    fake_settings.set_install_metadata.assert_not_called()


def _make_checkout(path: Path) -> Path:
    required = (
        "install.py",
        "package.json",
        "pyproject.toml",
        "src/basecamp/installer.py",
        "pi/extension.ts",
        "omp/package.json",
        "omp/extension.ts",
    )
    for relative in required:
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
    return path
