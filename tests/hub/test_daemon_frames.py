"""Contract tests for protocol frame fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, get_args, get_origin

from basecamp.hub.frames import (
    PROTOCOL_VERSION,
    AttachWorkstreamAgentAckFrame,
    AttachWorkstreamAgentFrame,
    CreateWorkstreamAckFrame,
    CreateWorkstreamFrame,
    Frame,
    ReviseWorkstreamAckFrame,
    ReviseWorkstreamFrame,
    UpdateWorkstreamAckFrame,
    UpdateWorkstreamFrame,
    parse_frame,
    serialize_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "pi" / "core" / "hub" / "protocol" / "frames"


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


def test_protocol_version_is_25() -> None:
    assert PROTOCOL_VERSION == 25


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


def test_protocol_version_defaults_without_explicit_v() -> None:
    """Frames construct without passing ``v``; the ProtocolFrame default fills it in."""

    frame = UpdateWorkstreamFrame(
        type="update_workstream",
        request_id="req-envelope",
        workstream="my-slug",
        status="open",
    )
    assert frame.v == PROTOCOL_VERSION
    # The default is "unset", so exclude_unset would drop it without stamping.
    assert "v" not in frame.model_dump(exclude_unset=True)


def test_serialize_frame_stamps_v_on_the_wire() -> None:
    """serialize_frame re-stamps ``v`` so the wire always carries the version."""

    frame = UpdateWorkstreamFrame(
        type="update_workstream",
        request_id="req-envelope",
        workstream="my-slug",
        status="open",
    )
    serialized = serialize_frame(frame)
    assert serialized["v"] == PROTOCOL_VERSION
    assert parse_frame(serialized) == frame


def test_create_workstream_frame_round_trip() -> None:
    frame = CreateWorkstreamFrame(
        type="create_workstream",
        v=PROTOCOL_VERSION,
        request_id="req-1",
        workstream_id="ws-1",
        slug="my-slug",
        label="My Workstream",
        brief="Do the thing",
        source_dossier_path="/dossiers/thing.md",
    )
    serialized = serialize_frame(frame)
    assert "constraints" not in serialized
    assert "source_repo_page_path" not in serialized
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, CreateWorkstreamFrame)
    assert reparsed == frame


def test_create_workstream_frame_with_optional_fields_round_trip() -> None:
    frame = CreateWorkstreamFrame(
        type="create_workstream",
        v=PROTOCOL_VERSION,
        request_id="req-2",
        workstream_id="ws-2",
        slug="my-slug-2",
        label="My Workstream 2",
        brief="Do the thing 2",
        source_dossier_path="/dossiers/thing2.md",
        constraints="must not break",
        source_repo_page_path="/repos/basecamp/README.md",
    )
    serialized = serialize_frame(frame)
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, CreateWorkstreamFrame)
    assert reparsed == frame


def test_create_workstream_ack_frame_round_trip() -> None:
    for status in ("created", "slug_conflict", "error"):
        frame = CreateWorkstreamAckFrame(
            type="create_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=f"req-{status}",
            status=status,
        )
        serialized = serialize_frame(frame)
        assert "workstream_id" not in serialized
        assert "slug" not in serialized
        reparsed = parse_frame(serialized)
        assert isinstance(reparsed, CreateWorkstreamAckFrame)
        assert reparsed == frame


def test_attach_workstream_agent_frame_round_trip() -> None:
    frame = AttachWorkstreamAgentFrame(
        type="attach_workstream_agent",
        v=PROTOCOL_VERSION,
        request_id="req-attach",
        workstream="my-slug",
    )
    serialized = serialize_frame(frame)
    assert "repo" not in serialized
    assert "worktree_label" not in serialized
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, AttachWorkstreamAgentFrame)
    assert reparsed == frame


def test_attach_workstream_agent_frame_with_optional_fields_round_trip() -> None:
    frame = AttachWorkstreamAgentFrame(
        type="attach_workstream_agent",
        v=PROTOCOL_VERSION,
        request_id="req-attach-2",
        workstream="ws-1",
        repo="org/repo",
        worktree_label="wt-bt/slug",
        status="attached",
        error=None,
    )
    serialized = serialize_frame(frame)
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, AttachWorkstreamAgentFrame)
    assert reparsed == frame


def test_attach_workstream_agent_ack_frame_round_trip() -> None:
    for status in ("attached", "not_found", "error"):
        frame = AttachWorkstreamAgentAckFrame(
            type="attach_workstream_agent_ack",
            v=PROTOCOL_VERSION,
            request_id=f"req-ack-{status}",
            status=status,
        )
        serialized = serialize_frame(frame)
        assert "error" not in serialized
        reparsed = parse_frame(serialized)
        assert isinstance(reparsed, AttachWorkstreamAgentAckFrame)
        assert reparsed == frame


def test_update_workstream_frame_round_trip() -> None:
    for status in ("open", "closed"):
        frame = UpdateWorkstreamFrame(
            type="update_workstream",
            v=PROTOCOL_VERSION,
            request_id=f"req-update-{status}",
            workstream="my-slug",
            status=status,
        )
        serialized = serialize_frame(frame)
        reparsed = parse_frame(serialized)
        assert isinstance(reparsed, UpdateWorkstreamFrame)
        assert reparsed == frame


def test_update_workstream_ack_frame_round_trip() -> None:
    for status in ("updated", "not_found", "invalid_status", "error"):
        frame = UpdateWorkstreamAckFrame(
            type="update_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=f"req-update-ack-{status}",
            status=status,
        )
        serialized = serialize_frame(frame)
        assert "error" not in serialized
        reparsed = parse_frame(serialized)
        assert isinstance(reparsed, UpdateWorkstreamAckFrame)
        assert reparsed == frame


def test_revise_workstream_frame_round_trip() -> None:
    frame = ReviseWorkstreamFrame(
        type="revise_workstream",
        v=PROTOCOL_VERSION,
        request_id="req-revise",
        workstream="my-slug",
        label="My Workstream v2",
        brief="Do the refined thing",
    )
    serialized = serialize_frame(frame)
    assert "constraints" not in serialized
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, ReviseWorkstreamFrame)
    assert reparsed == frame


def test_revise_workstream_ack_frame_round_trip() -> None:
    for status, version in (("revised", 3), ("not_found", None), ("error", None)):
        frame = ReviseWorkstreamAckFrame(
            type="revise_workstream_ack",
            v=PROTOCOL_VERSION,
            request_id=f"req-revise-ack-{status}",
            status=status,
            version=version,
        )
        serialized = serialize_frame(frame)
        assert "error" not in serialized
        reparsed = parse_frame(serialized)
        assert isinstance(reparsed, ReviseWorkstreamAckFrame)
        assert reparsed == frame
