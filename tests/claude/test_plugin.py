"""Tests for basecamp.claude.plugin — plugin registration via the ``claude`` CLI.

Registration shells out to ``claude plugin ...`` (writing settings.json alone
does not load a plugin — the cache the loader reads is built by ``plugin
install``). These tests mock the subprocess boundary and assert the exact command
sequence + the fail paths; the real end-to-end load is proven by the docker
sandbox.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from basecamp.claude import plugin
from basecamp.claude.plugin import (
    ENABLED_KEY,
    MARKETPLACE_NAME,
    PLUGIN_NAME,
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


def test_constants_match_committed_manifests() -> None:
    # The plugin/marketplace names are hardcoded constants; if a manifest is
    # renamed without updating them, registration writes a stale id and the plugin
    # silently never loads. Pin them to the committed manifests so a drift fails here.
    manifest_dir = Path(__file__).resolve().parents[2] / "claude" / ".claude-plugin"
    marketplace = json.loads((manifest_dir / "marketplace.json").read_text(encoding="utf-8"))
    plugin_manifest = json.loads((manifest_dir / "plugin.json").read_text(encoding="utf-8"))

    assert marketplace["name"] == MARKETPLACE_NAME
    assert plugin_manifest["name"] == PLUGIN_NAME
    assert [p["name"] for p in marketplace["plugins"]] == [PLUGIN_NAME]
    assert ENABLED_KEY == f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"


def test_register_tolerates_already_registered_marketplace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # On older Claude Code `marketplace add` errors if the marketplace already
    # exists; a re-run must still reach install + update, not skip the refresh.
    def add_says_exists(argv: list[str]) -> SimpleNamespace:
        if argv[1:4] == ["plugin", "marketplace", "add"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="marketplace 'basecamp' already exists")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    calls = _record_runs(monkeypatch, result_fn=add_says_exists)

    register_plugin(tmp_path)  # must not raise

    assert [c[1:3] for c in calls] == [
        ["plugin", "marketplace"],
        ["plugin", "install"],
        ["plugin", "marketplace"],
        ["plugin", "update"],
    ]


def test_register_still_raises_on_a_real_marketplace_add_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Tolerance is narrow: a non-"exists" failure on add still aborts registration.
    def add_fails(argv: list[str]) -> SimpleNamespace:
        if argv[1:4] == ["plugin", "marketplace", "add"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="source path does not exist")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    calls = _record_runs(monkeypatch, result_fn=add_fails)

    with pytest.raises(PluginRegistrationError, match="does not exist"):
        register_plugin(tmp_path)

    assert [c[1:3] for c in calls] == [["plugin", "marketplace"]]  # stopped at add


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
