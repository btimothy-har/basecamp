"""Tests for the non-blocking PostToolUse file-length warn hook."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import basecamp.hooks as hooks
from basecamp.hooks.file_length import LINE_CAP, handle_file_length


def _write_lines(path: Path, count: int) -> None:
    path.write_text("\n".join(f"line {i}" for i in range(count)), encoding="utf-8")


def _advisory(output: str | None) -> str:
    assert output is not None
    payload = json.loads(output)
    block = payload["hookSpecificOutput"]
    assert block["hookEventName"] == "PostToolUse"
    assert "decision" not in payload
    assert "decision" not in block
    return block["additionalContext"]


# --- over-cap → advisory emitted -------------------------------------------------


def test_over_cap_source_file_emits_advisory(tmp_path: Path) -> None:
    target = tmp_path / "big.py"
    _write_lines(target, LINE_CAP + 25)

    context = _advisory(handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}))

    assert "big.py" in context
    assert str(LINE_CAP + 25) in context
    assert str(LINE_CAP) in context


def test_edit_and_multiedit_are_also_checked(tmp_path: Path) -> None:
    target = tmp_path / "big.ts"
    _write_lines(target, LINE_CAP + 1)

    for tool in ("Edit", "MultiEdit"):
        assert handle_file_length({"tool_name": tool, "tool_input": {"file_path": str(target)}}) is not None


def test_relative_path_is_resolved_against_cwd(tmp_path: Path) -> None:
    target = tmp_path / "nested.py"
    _write_lines(target, LINE_CAP + 3)

    output = handle_file_length({"tool_name": "Write", "tool_input": {"file_path": "nested.py"}, "cwd": str(tmp_path)})

    assert "nested.py" in _advisory(output)


@pytest.mark.parametrize(
    ("name", "cap"),
    [
        ("query.sql", 800),
        ("page.html", 800),
        ("deploy.sh", 400),
        ("service.go", 500),  # unlisted type → general cap
    ],
)
def test_per_type_caps(tmp_path: Path, name: str, cap: int) -> None:
    """SQL/HTML get more room, shell less; an unlisted type falls to the general cap."""
    target = tmp_path / name

    _write_lines(target, cap)
    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is None

    _write_lines(target, cap + 1)
    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is not None


# --- under-cap / non-source / wrong tool → no warning ----------------------------


def test_at_cap_is_not_flagged(tmp_path: Path) -> None:
    target = tmp_path / "exact.py"
    _write_lines(target, LINE_CAP)

    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is None


def test_under_cap_is_not_flagged(tmp_path: Path) -> None:
    target = tmp_path / "small.py"
    _write_lines(target, 10)

    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is None


@pytest.mark.parametrize("name", ["data.json", "uv.lock", "notes.md", "config.yaml"])
def test_non_source_suffixes_are_exempt(tmp_path: Path, name: str) -> None:
    target = tmp_path / name
    _write_lines(target, LINE_CAP + 100)

    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is None


def test_non_write_tool_is_ignored(tmp_path: Path) -> None:
    target = tmp_path / "big.py"
    _write_lines(target, LINE_CAP + 50)

    assert handle_file_length({"tool_name": "Read", "tool_input": {"file_path": str(target)}}) is None


# --- malformed / missing input → fail-open (None, no raise) ----------------------


def test_missing_file_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "ghost.py"

    assert handle_file_length({"tool_name": "Write", "tool_input": {"file_path": str(target)}}) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"tool_name": "Write"},
        {"tool_name": "Write", "tool_input": None},
        {"tool_name": "Write", "tool_input": {}},
        {"tool_name": "Write", "tool_input": {"file_path": ""}},
        {"tool_name": "Write", "tool_input": {"file_path": 123}},
    ],
)
def test_malformed_payload_returns_none(payload: dict[str, object]) -> None:
    assert handle_file_length(payload) is None


# --- dispatcher wiring: main() prints the advisory, fails open -------------------


def test_dispatcher_writes_advisory_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    target = tmp_path / "big.py"
    _write_lines(target, LINE_CAP + 5)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}})),
    )

    assert hooks.main(["file-length"]) == 0
    assert "big.py" in _advisory(capsys.readouterr().out)


def test_dispatcher_stays_silent_under_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    target = tmp_path / "small.py"
    _write_lines(target, 5)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}})),
    )

    assert hooks.main(["file-length"]) == 0
    assert capsys.readouterr().out == ""


def test_file_length_is_wired_into_the_dispatcher() -> None:
    assert hooks._load_handler("file-length") is handle_file_length


def test_file_length_dispatch_does_not_import_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The per-edit file-length hook must not pull in the session module (hub client)."""
    monkeypatch.delitem(sys.modules, "basecamp.hooks.session", raising=False)
    target = tmp_path / "small.py"
    _write_lines(target, 5)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(target)}})),
    )

    assert hooks.main(["file-length"]) == 0
    assert "basecamp.hooks.session" not in sys.modules
