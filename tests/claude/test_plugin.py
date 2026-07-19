"""Tests for basecamp.claude.plugin — plugin registration via the ``claude`` CLI.

Registration shells out to ``claude plugin ...`` (writing settings.json alone
does not load a plugin — the cache the loader reads is built by ``plugin
install``). These tests mock the subprocess boundary and assert the exact command
sequence + the fail paths; the real end-to-end load is proven by the docker
sandbox.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from basecamp.claude import plugin
from basecamp.claude.plugin import (
    ENABLED_KEY,
    MARKETPLACE_NAME,
    PluginRegistrationError,
    plugin_dir,
    register_plugin,
)

_CLAUDE = "/usr/bin/claude"


def _ok(*_a: object, **_k: object) -> SimpleNamespace:
    return SimpleNamespace(returncode=0, stdout="ok", stderr="")


def _record_runs(monkeypatch: pytest.MonkeyPatch, result_fn=_ok) -> list[list[str]]:
    """Stub claude on PATH + subprocess.run; return the list of arg-vectors run."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(argv)
        return result_fn(argv)

    monkeypatch.setattr(plugin.shutil, "which", lambda _cmd: _CLAUDE)
    monkeypatch.setattr(plugin.subprocess, "run", fake_run)
    return calls


def test_plugin_dir_is_absolute(tmp_path: Path) -> None:
    got = plugin_dir(tmp_path / "checkout")
    assert got.is_absolute()
    assert got == (tmp_path / "checkout" / "claude").resolve()


def test_register_runs_expected_command_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record_runs(monkeypatch)
    install_dir = tmp_path / "checkout"

    register_plugin(install_dir)

    marketplace = str((install_dir / "claude").resolve())
    assert calls == [
        [_CLAUDE, "plugin", "marketplace", "add", marketplace],
        [_CLAUDE, "plugin", "install", ENABLED_KEY],
        [_CLAUDE, "plugin", "marketplace", "update", MARKETPLACE_NAME],
        [_CLAUDE, "plugin", "update", ENABLED_KEY],
    ]


def test_register_raises_when_claude_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plugin.shutil, "which", lambda _cmd: None)

    with pytest.raises(PluginRegistrationError, match="not on PATH"):
        register_plugin(tmp_path)


def test_register_raises_and_stops_on_command_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_on_install(argv: list[str]) -> SimpleNamespace:
        if argv[1:3] == ["plugin", "install"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    calls = _record_runs(monkeypatch, result_fn=fail_on_install)

    with pytest.raises(PluginRegistrationError, match="boom"):
        register_plugin(tmp_path)

    # Stops at the failing step: marketplace-add ran, install failed, no updates.
    assert [c[1:3] for c in calls] == [["plugin", "marketplace"], ["plugin", "install"]]


def test_register_wraps_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout_run(_argv: list[str], **_kwargs: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(plugin.shutil, "which", lambda _cmd: _CLAUDE)
    monkeypatch.setattr(plugin.subprocess, "run", timeout_run)

    with pytest.raises(PluginRegistrationError, match="could not run"):
        register_plugin(tmp_path)
