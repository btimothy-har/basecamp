"""Tests for the Claude Code transcript JSONL parser."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.hub.claude.transcript import parse_transcript


def _write(path: Path, *lines: str) -> Path:
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def test_keeps_dag_nodes_and_skips_uuidless_markers(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.jsonl",
        json.dumps({"uuid": "a", "parentUuid": None, "type": "user", "timestamp": "t1"}),
        json.dumps({"type": "mode", "mode": "work"}),  # marker, no uuid
        json.dumps({"type": "last-prompt", "leafUuid": "a"}),  # marker, leafUuid != uuid
        json.dumps({"uuid": "b", "parentUuid": "a", "type": "assistant", "timestamp": "t2"}),
    )

    nodes = parse_transcript(path)

    assert [n["uuid"] for n in nodes] == ["a", "b"]
    assert [n["type"] for n in nodes] == ["user", "assistant"]


def test_lifts_compaction_bridge_and_reroot(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.jsonl",
        json.dumps({"uuid": "root", "parentUuid": None, "type": "user"}),
        json.dumps(
            {
                "uuid": "boundary",
                "parentUuid": None,  # compaction re-roots the physical chain
                "type": "system",
                "subtype": "compact_boundary",
                "logicalParentUuid": "root",  # ...bridged logically to the pre-compaction leaf
            }
        ),
    )

    nodes = parse_transcript(path)

    boundary = next(n for n in nodes if n["uuid"] == "boundary")
    assert boundary["parent_uuid"] is None
    assert boundary["logical_parent_uuid"] == "root"


def test_seq_is_the_physical_line_index(tmp_path: Path) -> None:
    # seq counts file lines (including skipped markers), so it stays a faithful
    # physical-order hint even though reconstruction walks parent_uuid.
    path = _write(
        tmp_path / "t.jsonl",
        json.dumps({"uuid": "a", "type": "user"}),
        json.dumps({"type": "mode"}),  # line index 1, skipped
        json.dumps({"uuid": "b", "type": "assistant"}),
    )

    nodes = parse_transcript(path)

    assert [(n["uuid"], n["seq"]) for n in nodes] == [("a", 0), ("b", 2)]


def test_is_sidechain_normalized_to_int(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.jsonl",
        json.dumps({"uuid": "a", "type": "user", "isSidechain": False}),
        json.dumps({"uuid": "b", "type": "assistant", "isSidechain": True}),
        json.dumps({"uuid": "c", "type": "assistant"}),  # absent -> 0
    )

    nodes = parse_transcript(path)

    assert [n["is_sidechain"] for n in nodes] == [0, 1, 0]


def test_line_json_is_stored_verbatim(tmp_path: Path) -> None:
    raw = '{"uuid":"a","type":"user","extra":{"nested":[1,2,3]},"keep":"me"}'
    path = _write(tmp_path / "t.jsonl", raw)

    nodes = parse_transcript(path)

    assert nodes[0]["line_json"] == raw
    assert json.loads(nodes[0]["line_json"])["keep"] == "me"


def test_blank_malformed_and_non_object_lines_are_skipped(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "t.jsonl",
        json.dumps({"uuid": "a", "type": "user"}),
        "",  # blank
        "{ not json",  # malformed
        json.dumps([1, 2, 3]),  # valid JSON, not an object
        json.dumps({"uuid": "b", "type": "assistant"}),
    )

    nodes = parse_transcript(path)

    assert [n["uuid"] for n in nodes] == ["a", "b"]


def test_empty_file_yields_no_nodes(tmp_path: Path) -> None:
    path = _write(tmp_path / "t.jsonl")

    assert parse_transcript(path) == []


def test_invalid_utf8_line_is_skipped_and_good_prefix_kept(tmp_path: Path) -> None:
    # A line truncated mid-multibyte character (the mid-write case PreCompact reads)
    # is invalid UTF-8. Strict decoding would raise UnicodeDecodeError from the file
    # iterator and lose every already-parsed node; replacement decoding must skip only
    # the bad line and keep the good prefix (and any good lines after it).
    good_before = json.dumps({"uuid": "a", "type": "user"}).encode("utf-8")
    good_after = json.dumps({"uuid": "b", "type": "assistant"}).encode("utf-8")
    truncated_multibyte = b'{"uuid":"bad","note":"\xe2\x82'  # '\xe2\x82' starts € but is cut off
    path = tmp_path / "t.jsonl"
    path.write_bytes(good_before + b"\n" + truncated_multibyte + b"\n" + good_after + b"\n")

    nodes = parse_transcript(path)

    assert [n["uuid"] for n in nodes] == ["a", "b"]
