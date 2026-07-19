"""Tests for basecamp.install.execute_install — the re-runnable wiring routine.

Plugin registration (``register_plugin``) shells out to the ``claude`` CLI and is
covered on its own in ``test_plugin.py`` / the docker sandbox; here it is stubbed
so these tests stay hermetic and assert the *orchestration* (dirs, doctrine,
config, and that registration is invoked / skipped / fail-soft).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basecamp import install
from basecamp.claude.plugin import PluginRegistrationError
from basecamp.core.projects import load_projects
from basecamp.core.settings import Settings


def _prepare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, install_dir: Path | None) -> Settings:
    """Point the installer at a temp HOME/config and stub the prompt source.

    Returns the temp ``Settings`` so the caller can read back what was seeded.
    """
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    test_settings = Settings(tmp_path / "config.json")
    if install_dir is not None:
        test_settings.set_install_metadata(install_dir=str(install_dir))
    monkeypatch.setattr(install, "settings", test_settings)
    monkeypatch.setattr("basecamp.core.projects.settings", test_settings)

    context_dir = tmp_path / "context"
    monkeypatch.setattr(install, "USER_CONTEXT_DIR", context_dir)

    prompts = tmp_path / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "doctrine.md").write_text("# doctrine\n\nrule one\n", encoding="utf-8")
    monkeypatch.setattr(install, "shipped_prompts_dir", lambda: prompts)

    return test_settings


def test_execute_install_full(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    checkout = home / "checkout"  # under HOME so to_home_relative() succeeds
    test_settings = _prepare(monkeypatch, tmp_path, install_dir=checkout)

    registered: list[Path] = []
    monkeypatch.setattr(install, "register_plugin", lambda d: registered.append(d))

    install.execute_install()

    # Context dir scaffolded; styles/prompts scaffolds are gone.
    assert (tmp_path / "context").is_dir()
    assert not (tmp_path / "styles").exists()
    assert not (tmp_path / "prompts" / "styles").exists()

    # Doctrine written into the temp ~/.claude/CLAUDE.md.
    doctrine = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "rule one" in doctrine

    # Plugin registration invoked with the recorded install_dir.
    assert registered == [checkout]

    # Default project seeded without the retired working_style field.
    projects = load_projects(config=test_settings)
    assert "basecamp" in projects
    assert "working_style" not in projects["basecamp"].model_dump()


def test_register_plugin_skipped_when_install_dir_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _prepare(monkeypatch, tmp_path, install_dir=None)

    called = False

    def _should_not_run(_d: Path) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(install, "register_plugin", _should_not_run)

    # No install_dir recorded → registration is a graceful no-op, no exception.
    install._register_plugin()

    assert called is False


def test_execute_install_survives_plugin_registration_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    checkout = home / "checkout"
    test_settings = _prepare(monkeypatch, tmp_path, install_dir=checkout)

    def _boom(_d: Path) -> None:
        msg = "the `claude` CLI is not on PATH"
        raise PluginRegistrationError(msg)

    monkeypatch.setattr(install, "register_plugin", _boom)

    # Fail-soft: a registration failure must not abort the rest of the install.
    install.execute_install()

    assert (home / ".claude" / "CLAUDE.md").exists()  # doctrine still installed
    assert "basecamp" in load_projects(config=test_settings)  # config still seeded
