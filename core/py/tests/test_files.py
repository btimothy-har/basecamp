"""Tests for basecamp.core.files — atomic_write_json."""

from __future__ import annotations

import json
import os
from pathlib import Path

from basecamp.core.files import atomic_write_json


class TestAtomicWriteJson:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "deep" / "config.json"
        atomic_write_json(path, {"a": 1})

        assert path.exists()
        assert json.loads(path.read_text()) == {"a": 1}

    def test_writes_valid_indented_json(self, tmp_path: Path) -> None:
        path = tmp_path / "out.json"
        atomic_write_json(path, {"b": [1, 2], "c": "x"})

        text = path.read_text()
        # Indented (two-space) and trailing newline.
        assert '\n  "b"' in text
        assert text.endswith(os.linesep)
        assert json.loads(text) == {"b": [1, 2], "c": "x"}

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "out.json"
        atomic_write_json(path, {"v": 1})
        atomic_write_json(path, {"v": 2})

        assert json.loads(path.read_text()) == {"v": 2}

    def test_writes_list_payload(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        atomic_write_json(path, [1, 2, 3])

        assert json.loads(path.read_text()) == [1, 2, 3]

    def test_sets_file_permissions(self, tmp_path: Path) -> None:
        path = tmp_path / "secret.json"
        atomic_write_json(path, {"x": 1}, mode=0o600)

        mode = path.stat().st_mode & 0o777
        assert mode == 0o600
