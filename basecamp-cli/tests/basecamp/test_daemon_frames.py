"""Contract tests for protocol frame fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from basecamp.daemon.frames import (
    DispatchAckFrame,
    DispatchFrame,
    ErrorFrame,
    RegisteredFrame,
    RegisterFrame,
    ResultReportFrame,
    TelemetryFrame,
    WaitFrame,
    WaitResultFrame,
    parse_frame,
    serialize_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "protocol" / "frames"


@pytest.mark.parametrize(
    ("fixture_name", "expected_type"),
    [
        ("register.json", RegisterFrame),
        ("registered.json", RegisteredFrame),
        ("error.json", ErrorFrame),
        ("dispatch.json", DispatchFrame),
        ("dispatch_ack.json", DispatchAckFrame),
        ("telemetry.json", TelemetryFrame),
        ("result_report.json", ResultReportFrame),
        ("wait.json", WaitFrame),
        ("wait_result.json", WaitResultFrame),
    ],
)
def test_fixture_parses_and_round_trips(fixture_name: str, expected_type: type) -> None:
    fixture_path = FIXTURE_DIR / fixture_name
    data = json.loads(fixture_path.read_text(encoding="utf-8"))

    frame = parse_frame(data)
    assert isinstance(frame, expected_type)

    serialized = serialize_frame(frame)
    reparsed = parse_frame(serialized)
    assert isinstance(reparsed, expected_type)
    assert serialized == data
