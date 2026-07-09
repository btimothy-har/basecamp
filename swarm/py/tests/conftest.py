"""Shared fixtures for swarm daemon tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def _isolate_run_result_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
