import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import basecamp.installer as installer


def _completed(stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = stdout
    result.stderr = ""
    return result


def _make_checkout(path: Path) -> Path:
    entry = path / installer.WORKSPACE_EXTENSION_ENTRY
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("// workspace extension\n")
    return path


def _run_install(mocker, checkout: Path, agent_dir: Path, *, previous: Path | None = None) -> None:
    mocker.patch.object(
        installer.subprocess,
        "run",
        return_value=_completed(stdout=f"{agent_dir}\n"),
    )
    mocker.patch.object(
        installer,
        "settings",
        MagicMock(install_dir=str(previous) if previous else None),
    )
    installer._register_omp_workspace_extension("/usr/bin/omp", checkout)


def _manifest_path(agent_dir: Path) -> Path:
    return agent_dir / "extensions" / installer.WORKSPACE_REGISTRATION / "package.json"


def _expected_manifest(checkout: Path) -> dict[str, object]:
    return {
        "name": "basecamp-workspace",
        "private": True,
        "omp": {"extensions": [str((checkout / installer.WORKSPACE_EXTENSION_ENTRY).resolve())]},
    }


def test_registration_creates_managed_manifest(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"

    _run_install(mocker, checkout, agent_dir)

    assert json.loads(_manifest_path(agent_dir).read_text()) == _expected_manifest(checkout)


def test_registration_is_idempotent(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"

    _run_install(mocker, checkout, agent_dir)
    first = _manifest_path(agent_dir).read_text()
    _run_install(mocker, checkout, agent_dir)

    assert _manifest_path(agent_dir).read_text() == first


def test_registration_retargets_previously_recorded_checkout(mocker, tmp_path: Path) -> None:
    previous = _make_checkout(tmp_path / "previous")
    current = _make_checkout(tmp_path / "current")
    agent_dir = tmp_path / "agent"

    _run_install(mocker, previous, agent_dir)
    _run_install(mocker, current, agent_dir, previous=previous)

    assert json.loads(_manifest_path(agent_dir).read_text()) == _expected_manifest(current)


def test_registration_preserves_user_modified_manifest(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    manifest = _manifest_path(agent_dir)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "basecamp-workspace", "private": False}) + "\n")

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert json.loads(manifest.read_text())["private"] is False


def test_registration_preserves_foreign_manifest_pointing_elsewhere(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    manifest = _manifest_path(agent_dir)
    manifest.parent.mkdir(parents=True)
    foreign = {
        "name": "basecamp-workspace",
        "private": True,
        "omp": {"extensions": [str(tmp_path / "elsewhere" / "extension.ts")]},
    }
    manifest.write_text(json.dumps(foreign) + "\n")

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert json.loads(manifest.read_text()) == foreign


def test_registration_preserves_malformed_manifest(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    manifest = _manifest_path(agent_dir)
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{not json\n")

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert manifest.read_text() == "{not json\n"


def test_registration_refuses_symlink_manifest(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    manifest = _manifest_path(agent_dir)
    manifest.parent.mkdir(parents=True)
    target = tmp_path / "owned.json"
    target.write_text(json.dumps(_expected_manifest(checkout)))
    manifest.symlink_to(target)

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert manifest.is_symlink()


def test_registration_refuses_symlink_registration_dir(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    registration_dir = agent_dir / "extensions" / installer.WORKSPACE_REGISTRATION
    registration_dir.parent.mkdir(parents=True)
    registration_dir.symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert registration_dir.is_symlink()
    assert not (elsewhere / "package.json").exists()


def test_registration_refuses_nonempty_unowned_directory(mocker, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    agent_dir = tmp_path / "agent"
    registration_dir = agent_dir / "extensions" / installer.WORKSPACE_REGISTRATION
    registration_dir.mkdir(parents=True)
    foreign = registration_dir / "index.ts"
    foreign.write_text("// user extension\n")

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert foreign.read_text() == "// user extension\n"
    assert not (registration_dir / "package.json").exists()


def test_registration_requires_workspace_entrypoint(mocker, tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    agent_dir = tmp_path / "agent"

    with pytest.raises(SystemExit):
        _run_install(mocker, checkout, agent_dir)

    assert not (agent_dir / "extensions").exists()
