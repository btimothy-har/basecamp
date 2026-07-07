"""Protocol frame models for the pi-swarm daemon."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

# Gates every client-visible daemon capability, not just WebSocket frame shapes.
# This includes HTTP endpoints like /runs/summary, so stale daemons restart.
# v18: cancel-agent request/ack frames.
PROTOCOL_VERSION = 18


class RegisterFrame(BaseModel):
    """Client registration frame."""

    type: Literal["register"]
    v: Literal[PROTOCOL_VERSION]
    role: Literal["session", "agent"]
    node_id: str
    agent_handle: str | None = None
    parent_id: str | None
    sibling_group: str | None
    depth: int
    session_name: str
    cwd: str
    session_file: str | None = None
    product_role: str | None = None


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
    fork_from: str | None = None
    task: str


class DispatchFrame(BaseModel):
    """Dispatch request frame."""

    type: Literal["dispatch"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    agent_id: str | None = None
    agent_handle: str | None = None
    agent_type: str | None = None
    run_kind: str | None = None
    model: str | None = None
    spec: DispatchSpec


class DispatchAckFrame(BaseModel):
    """Dispatch acknowledgement frame."""

    type: Literal["dispatch_ack"]
    v: Literal[PROTOCOL_VERSION]
    run_id: str
    status: Literal["spawned", "rejected"]
    reason: str | None = None


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
    agent_ids: list[str] = Field(default_factory=list)
    agent_handles: list[str] = Field(default_factory=list)
    mode: Literal["all"]
    timeout_s: float


class WaitResultItem(BaseModel):
    """Single wait result item."""

    agent_id: str | None = None
    agent_handle: str | None = None
    status: Literal["completed", "failed", "running", "unknown"]
    result: str | None = None
    error: str | None = None


class WaitResultFrame(BaseModel):
    """Wait response frame."""

    type: Literal["wait_result"]
    v: Literal[PROTOCOL_VERSION]
    results: list[WaitResultItem]


class ListAgentsFrame(BaseModel):
    """Request list of agents in requester root scope."""

    type: Literal["list_agents"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    awaitable: bool = False


class ListAgentItem(BaseModel):
    """Single list-agents row."""

    agent_id: str
    agent_handle: str | None = None
    agent_type: str | None = None
    run_kind: str | None = None
    parent_id: str | None
    role: str
    session_name: str
    depth: int
    status: Literal["pending", "running", "completed", "failed", "idle"]
    awaitable: bool
    task: str | None = None


class ListAgentsResultFrame(BaseModel):
    """List-agents response frame."""

    type: Literal["list_agents_result"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    agents: list[ListAgentItem]


class PeerMessageFrame(BaseModel):
    """Request asynchronous delivery of a peer message."""

    type: Literal["peer_message"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    target_handle: str
    message: str
    interrupt: bool = False


class PeerMessageAckFrame(BaseModel):
    """Acceptance acknowledgement for a peer message request."""

    type: Literal["peer_message_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str | None
    status: Literal["accepted", "unknown"]
    error: str | None = None


PeerMessageRelation = Literal["self", "parent", "ancestor", "child", "descendant", "peer", "unknown"]


class PeerMessageDeliveryFrame(BaseModel):
    """Peer message delivery from daemon to recipient agent."""

    type: Literal["peer_message_delivery"]
    v: Literal[PROTOCOL_VERSION]
    message_id: str
    from_handle: str | None
    from_relation: PeerMessageRelation
    from_product_role: str | None = None
    message: str
    interrupt: bool


class PeerMessageDeliveryAckFrame(BaseModel):
    """Recipient acknowledgement that a peer message delivery was queued."""

    type: Literal["peer_message_delivery_ack"]
    v: Literal[PROTOCOL_VERSION]
    message_id: str
    status: Literal["queued", "failed"]
    error: str | None = None


class MessageStatusFrame(BaseModel):
    """Request delivery lifecycle status for a peer message."""

    type: Literal["message_status"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str
    wait_until_delivery: bool = False
    timeout_s: float | None = None


class MessageStatusResultFrame(BaseModel):
    """Delivery lifecycle status for a peer message."""

    type: Literal["message_status_result"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    message_id: str
    status: Literal["accepted", "sent", "queued", "failed", "unavailable", "unknown"]
    error: str | None = None
    created_at: str | None
    sent_at: str | None
    queued_at: str | None
    failed_at: str | None


class CancelFrame(BaseModel):
    """Request cancellation of an agent's current run."""

    type: Literal["cancel"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    target_handle: str


class CancelAckFrame(BaseModel):
    """Acknowledgement for a cancel request."""

    type: Literal["cancel_ack"]
    v: Literal[PROTOCOL_VERSION]
    request_id: str
    status: Literal["cancelled", "not_found", "not_authorized", "already_terminal"]
    error: str | None = None


Frame = Annotated[
    RegisterFrame
    | RegisteredFrame
    | ErrorFrame
    | DispatchFrame
    | DispatchAckFrame
    | TelemetryFrame
    | ResultReportFrame
    | WaitFrame
    | WaitResultFrame
    | ListAgentsFrame
    | ListAgentsResultFrame
    | PeerMessageFrame
    | PeerMessageAckFrame
    | PeerMessageDeliveryFrame
    | PeerMessageDeliveryAckFrame
    | MessageStatusFrame
    | MessageStatusResultFrame
    | CancelFrame
    | CancelAckFrame,
    Field(discriminator="type"),
]


_FRAME_ADAPTER = TypeAdapter(Frame)


def parse_frame(data: dict[str, Any]) -> Frame:
    """Parse an inbound dict into a protocol frame union."""

    return _FRAME_ADAPTER.validate_python(data)


def serialize_frame(frame: Frame) -> dict[str, Any]:
    """Serialize a frame model into JSON-compatible dict form."""

    return frame.model_dump(mode="json", exclude_unset=True)
