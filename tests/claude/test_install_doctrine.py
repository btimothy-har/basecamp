"""Tests for the doctrine managed-block install in basecamp.install."""

from __future__ import annotations

from pathlib import Path

import pytest

from basecamp import install
from basecamp.install import _DOCTRINE_BEGIN, _DOCTRINE_END, _install_doctrine, _upsert_managed_block

_BLOCK = f"{_DOCTRINE_BEGIN}\nDOCTRINE BODY\n{_DOCTRINE_END}"


def test_upsert_into_empty() -> None:
    assert _upsert_managed_block("", _BLOCK) == _BLOCK + "\n"


def test_upsert_appends_preserving_content() -> None:
    result = _upsert_managed_block("# My notes\n\nkeep me\n", _BLOCK)
    assert "# My notes" in result
    assert "keep me" in result
    assert result.count(_DOCTRINE_BEGIN) == 1
    assert result.endswith(_BLOCK + "\n")


def test_upsert_replaces_existing_block() -> None:
    seeded = f"top\n\n{_DOCTRINE_BEGIN}\nOLD\n{_DOCTRINE_END}\n\nbottom\n"
    new_block = f"{_DOCTRINE_BEGIN}\nNEW\n{_DOCTRINE_END}"
    result = _upsert_managed_block(seeded, new_block)
    assert "top" in result
    assert "bottom" in result
    assert "OLD" not in result
    assert "NEW" in result
    assert result.count(_DOCTRINE_BEGIN) == 1
    assert result.count(_DOCTRINE_END) == 1


def test_upsert_desynced_markers_preserve_user_content() -> None:
    # Orphaned BEGIN (END manually deleted) followed by a valid block, with user
    # content wedged between: the splice must NOT eat "notes B".
    orphan = f"{_DOCTRINE_BEGIN}\nnotes B\n\n{_DOCTRINE_BEGIN}\nOLD\n{_DOCTRINE_END}\n"
    new_block = f"{_DOCTRINE_BEGIN}\nNEW\n{_DOCTRINE_END}"
    result = _upsert_managed_block(orphan, new_block)
    assert "notes B" in result
    assert "NEW" in result


def _patch_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "doctrine.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(install, "shipped_prompts_dir", lambda: prompts)


def test_install_doctrine_creates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _patch_source(monkeypatch, tmp_path, "# Engineering doctrine\n\nrule one\n")

    assert _install_doctrine() is True

    dest = home / ".claude" / "CLAUDE.md"
    text = dest.read_text(encoding="utf-8")
    assert _DOCTRINE_BEGIN in text
    assert "rule one" in text


def test_install_doctrine_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    dest = home / ".claude" / "CLAUDE.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("# user content\n", encoding="utf-8")

    _patch_source(monkeypatch, tmp_path, "v1\n")
    _install_doctrine()
    _patch_source(monkeypatch, tmp_path, "v2\n")
    _install_doctrine()

    text = dest.read_text(encoding="utf-8")
    assert "# user content" in text
    assert text.count(_DOCTRINE_BEGIN) == 1
    assert "v1" not in text
    assert "v2" in text


def test_install_doctrine_missing_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(install, "shipped_prompts_dir", lambda: tmp_path / "nope")

    assert _install_doctrine() is False
    assert not (home / ".claude" / "CLAUDE.md").exists()
