from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _load_installer_module() -> Any:
    module_path = Path(__file__).resolve().parents[2] / "install.py"
    spec = importlib.util.spec_from_file_location("bc_swarm_install_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_run_factory(calls: list[tuple[tuple[str, ...], dict[str, object] | None]]) -> Any:
    def fake_run(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((tuple(args), kwargs))
        return SimpleNamespace(returncode=0, stderr="")

    return fake_run


def test_install_python_tool_constructs_editable_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install = _load_installer_module()
    calls: list[tuple[tuple[str, ...], dict[str, object] | None]] = []
    monkeypatch.setattr(install.shutil, "which", lambda command: "/usr/bin/uv" if command == "uv" else None)
    monkeypatch.setattr(install.subprocess, "run", _fake_run_factory(calls))

    install.install_python_tool(tmp_path / "daemon-cli", "bc-swarm", editable=True)

    assert len(calls) == 1
    captured_args, captured_kwargs = calls[0]
    assert captured_args == (
        "/usr/bin/uv",
        "tool",
        "install",
        "--force",
        "--reinstall",
        "-e",
        str(tmp_path / "daemon-cli"),
    )
    assert captured_kwargs is not None
    assert captured_kwargs.get("check") is False
    assert captured_kwargs.get("capture_output") is True
    assert captured_kwargs.get("text") is True


def test_install_python_tool_constructs_non_editable_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install = _load_installer_module()
    calls: list[tuple[tuple[str, ...], dict[str, object] | None]] = []
    monkeypatch.setattr(install.shutil, "which", lambda command: "/usr/bin/uv" if command == "uv" else None)
    monkeypatch.setattr(install.subprocess, "run", _fake_run_factory(calls))

    install.install_python_tool(tmp_path / "daemon-cli", "bc-swarm", editable=False)

    assert len(calls) == 1
    assert calls[0][0] == ("/usr/bin/uv", "tool", "install", "--force", "--reinstall", str(tmp_path / "daemon-cli"))


def test_install_python_tool_exits_when_uv_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install = _load_installer_module()
    calls: list[tuple[tuple[str, ...], dict[str, object] | None]] = []
    monkeypatch.setattr(install.shutil, "which", lambda _command: None)
    monkeypatch.setattr(install.subprocess, "run", _fake_run_factory(calls))

    with pytest.raises(SystemExit) as exc:
        install.install_python_tool(tmp_path / "daemon-cli", "bc-swarm", editable=False)

    assert exc.value.code == 1
    assert calls == []


def test_parse_editable_defaults_to_non_editable_without_interactive_input(monkeypatch: pytest.MonkeyPatch) -> None:
    install = _load_installer_module()
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError))

    assert install.parse_editable() is False


def test_install_pi_package_installs_npm_dependencies_and_registers_with_pi(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    install = _load_installer_module()
    calls: list[tuple[tuple[str, ...], dict[str, object] | None]] = []
    monkeypatch.setattr(install.shutil, "which", lambda command: "/usr/bin/npm" if command == "npm" else "/usr/bin/pi")
    monkeypatch.setattr(install.subprocess, "run", _fake_run_factory(calls))

    install.install_pi_package(tmp_path, "pi-swarm extension")

    assert len(calls) == 2
    assert calls[0][0] == ("/usr/bin/npm", "install")
    assert calls[0][1].get("cwd") == tmp_path
    assert calls[1][0] == ("/usr/bin/pi", "install", str(tmp_path))


def test_install_pi_package_skips_pi_install_when_pi_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install = _load_installer_module()
    calls: list[tuple[tuple[str, ...], dict[str, object] | None]] = []
    monkeypatch.setattr(install.shutil, "which", lambda command: "/usr/bin/npm" if command == "npm" else None)
    monkeypatch.setattr(install.subprocess, "run", _fake_run_factory(calls))

    install.install_pi_package(tmp_path, "pi-swarm extension")

    assert len(calls) == 1
    assert calls[0][0] == ("/usr/bin/npm", "install")
