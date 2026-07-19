from pathlib import Path
from unittest.mock import MagicMock

import basecamp.installer as installer


def _completed(returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stderr = ""
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

    installer._install_pi_extension()

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

    installer._uninstall_legacy_pi_packages("/usr/bin/pi")

    assert run.call_count == len(installer._LEGACY_PACKAGE_SUBPATHS)


def test_repo_dir_is_the_pi_extension_root() -> None:
    # The repo root carries the package manifest the installer registers; the
    # extension entry point itself lives under pi/.
    assert (Path(installer.REPO_DIR) / "pi" / "extension.ts").exists()
    assert (Path(installer.REPO_DIR) / "package.json").exists()
