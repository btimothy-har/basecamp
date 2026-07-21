"""Protocol frame models for the basecamp hub daemon.

Split by concern: ``version`` (the leaf ``PROTOCOL_VERSION``) and ``swarm``
(agent-coordination frames). This package owns the connection-envelope frames and the discriminated ``Frame``
union, and re-exports every frame so ``from ..frames import X`` keeps working.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from .swarm import (
    AttachWorkstreamAgentAckFrame,
    AttachWorkstreamAgentFrame,
    CancelAckFrame,
    CancelFrame,
    CreateWorkstreamAckFrame,
    CreateWorkstreamFrame,
    DispatchAckFrame,
    DispatchFrame,
    DispatchSpec,
    ListAgentItem,
    ListAgentsFrame,
    ListAgentsResultFrame,
    MessageStatusFrame,
    MessageStatusResultFrame,
    PeerMessageAckFrame,
    PeerMessageDeliveryAckFrame,
    PeerMessageDeliveryFrame,
    PeerMessageFrame,
    PeerMessageRelation,
    ResultReportFrame,
    ReviseWorkstreamAckFrame,
    ReviseWorkstreamFrame,
    TelemetryFrame,
    UpdateWorkstreamAckFrame,
    UpdateWorkstreamFrame,
    WaitFrame,
    WaitResultFrame,
    WaitResultItem,
)
from .version import PROTOCOL_VERSION, ProtocolFrame


class RegisterFrame(ProtocolFrame):
    """Client registration frame."""

    type: Literal["register"]
    role: Literal["agent", "worker"]
    node_id: str
    agent_handle: str | None = None
    parent_id: str | None
    sibling_group: str | None
    depth: int
    session_name: str
    cwd: str
    session_file: str | None = None
    repo: str | None = None
    worktree_label: str | None = None


class RegisteredFrame(ProtocolFrame):
    """Daemon registration acknowledgement frame."""

    type: Literal["registered"]
    node_id: str
    protocol: Literal[PROTOCOL_VERSION]


class ErrorFrame(ProtocolFrame):
    """Daemon error frame."""

    type: Literal["error"]
    code: str
    message: str


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
    | CancelAckFrame
    | CreateWorkstreamFrame
    | CreateWorkstreamAckFrame
    | AttachWorkstreamAgentFrame
    | AttachWorkstreamAgentAckFrame
    | UpdateWorkstreamFrame
    | UpdateWorkstreamAckFrame
    | ReviseWorkstreamFrame
    | ReviseWorkstreamAckFrame,
    Field(discriminator="type"),
]


_FRAME_ADAPTER = TypeAdapter(Frame)


def parse_frame(data: dict[str, Any]) -> Frame:
    """Parse an inbound dict into a protocol frame union."""

    return _FRAME_ADAPTER.validate_python(data)


def serialize_frame(frame: Frame) -> dict[str, Any]:
    """Serialize a frame model into JSON-compatible dict form.

    ``v`` is re-stamped here: construction sites rely on the ``ProtocolFrame``
    default rather than passing ``v``, and ``exclude_unset`` would otherwise
    drop the defaulted value from the wire.
    """

    data = frame.model_dump(mode="json", exclude_unset=True)
    data["v"] = PROTOCOL_VERSION
    return data


__all__ = [
    "PROTOCOL_VERSION",
    "AttachWorkstreamAgentAckFrame",
    "AttachWorkstreamAgentFrame",
    "CancelAckFrame",
    "CancelFrame",
    "CreateWorkstreamAckFrame",
    "CreateWorkstreamFrame",
    "DispatchAckFrame",
    "DispatchFrame",
    "DispatchSpec",
    "ErrorFrame",
    "Frame",
    "ListAgentItem",
    "ListAgentsFrame",
    "ListAgentsResultFrame",
    "MessageStatusFrame",
    "MessageStatusResultFrame",
    "PeerMessageAckFrame",
    "PeerMessageDeliveryAckFrame",
    "PeerMessageDeliveryFrame",
    "PeerMessageFrame",
    "PeerMessageRelation",
    "RegisterFrame",
    "RegisteredFrame",
    "ResultReportFrame",
    "ReviseWorkstreamAckFrame",
    "ReviseWorkstreamFrame",
    "TelemetryFrame",
    "UpdateWorkstreamAckFrame",
    "UpdateWorkstreamFrame",
    "WaitFrame",
    "WaitResultFrame",
    "WaitResultItem",
    "parse_frame",
    "serialize_frame",
]
