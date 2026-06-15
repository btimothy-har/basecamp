"""Contract tests for protocol frame fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, get_args, get_origin

from basecamp.daemon.frames import Frame, parse_frame, serialize_frame

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "pi-swarm" / "protocol" / "frames"


def _fixture_type_set() -> set[str]:
    return {path.stem for path in FIXTURE_DIR.glob("*.json")}


def _frame_union_type_set() -> set[str]:
    frame_union = get_args(Frame)[0]
    frame_types: set[str] = set()

    for model in get_args(frame_union):
        type_field = model.model_fields["type"]
        annotation = type_field.annotation
        if get_origin(annotation) is not Literal:
            continue
        frame_types.update(str(value) for value in get_args(annotation))

    return frame_types


def test_fixture_file_set_matches_frame_union_discriminator_types() -> None:
    assert _fixture_type_set() == _frame_union_type_set()


def test_all_fixtures_parse_and_round_trip() -> None:
    for fixture_path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(fixture_path.read_text(encoding="utf-8"))

        frame = parse_frame(data)
        assert frame.type == fixture_path.stem

        serialized = serialize_frame(frame)
        reparsed = parse_frame(serialized)
        assert reparsed.type == fixture_path.stem
        assert serialized == data
