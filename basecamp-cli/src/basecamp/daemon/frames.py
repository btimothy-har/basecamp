"""Protocol frame models for the basecamp daemon."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

PROTOCOL_VERSION = 2


class RegisterFrame(BaseModel):
    """Client registration frame."""

    type: Literal["register"]
    v: Literal[PROTOCOL_VERSION]
    role: Literal["session", "agent"]
    node_id: str
    parent_id: str | None
    sibling_group: str | None
    depth: int
    session_name: str
    cwd: str


class RegisteredFrame(BaseModel):
    """Daemon registration acknowledgement frame."""

    type: Literal["registered"]
    v: Literal[PROTOCOL_VERSION]
    node_id: str
    protocol: Literal[PROTOCOL_VERSION]


class ErrorFrame(BaseModel):
    """Daemon error frame."""

    type: Literal["error"]
    v: Literal[PROTOCOL_VERSION]
    code: str
    message: str


class DispatchSpec(BaseModel):
    """Run launch specification."""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    resume_path: str | None
    task: str


class DispatchFrame(BaseModel):
    """Dispatch request frame."""

    type: Literal["dispatch"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str | None = None
    spec: DispatchSpec


class DispatchAckFrame(BaseModel):
    """Dispatch acknowledgement frame."""

    type: Literal["dispatch_ack"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    status: Literal["spawned", "rejected"]
    reason: str | None


class TelemetryFrame(BaseModel):
    """Telemetry frame from an agent."""

    type: Literal["telemetry"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str
    report_token: str
    kind: str
    payload: dict[str, Any]


class ResultReportFrame(BaseModel):
    """Terminal result-report frame."""

    type: Literal["result_report"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str
    report_token: str
    status: Literal["ok", "error"]
    result: str | None
    error: str | None
    usage: dict[str, Any] | None


class WaitFrame(BaseModel):
    """Wait request frame."""

    type: Literal["wait"]
    v: Literal[PROTOCOL_VERSION]
    run_ids: list[str]
    mode: Literal["all"]
    timeout_s: float


class WaitResultItem(BaseModel):
    """Single wait result item."""

    run_id: str
    status: Literal["completed", "failed", "running", "unknown"]
    result: str | None
    error: str | None


class WaitResultFrame(BaseModel):
    """Wait response frame."""

    type: Literal["wait_result"]
    v: Literal[PROTOCOL_VERSION]
    results: list[WaitResultItem]


Frame = Annotated[
    RegisterFrame
    | RegisteredFrame
    | ErrorFrame
    | DispatchFrame
    | DispatchAckFrame
    | TelemetryFrame
    | ResultReportFrame
    | WaitFrame
    | WaitResultFrame,
    Field(discriminator="type"),
]


_FRAME_ADAPTER = TypeAdapter(Frame)


def parse_frame(data: dict[str, Any]) -> Frame:
    """Parse an inbound dict into a protocol frame union."""

    return _FRAME_ADAPTER.validate_python(data)


def serialize_frame(frame: Frame) -> dict[str, Any]:
    """Serialize a frame model into JSON-compatible dict form."""

    return frame.model_dump(mode="json")
