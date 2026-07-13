"""Protocol frame models for the basecamp hub daemon.

Split by concern: ``version`` (the leaf ``PROTOCOL_VERSION``), ``swarm``
(agent-coordination frames), and ``broker`` (companion analysis frames). This
package owns the connection-envelope frames and the discriminated ``Frame``
union, and re-exports every frame so ``from ..frames import X`` keeps working.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from .broker import ThreadReportFrame, ThreadReportNode
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
    TelemetryFrame,
    UpdateWorkstreamAckFrame,
    UpdateWorkstreamFrame,
    WaitFrame,
    WaitResultFrame,
    WaitResultItem,
)
from .version import PROTOCOL_VERSION


class RegisterFrame(BaseModel):
    """Client registration frame."""

    type: Literal["register"]
    v: Literal[PROTOCOL_VERSION]
    role: Literal["agent", "worker"]
    node_id: str
    agent_handle: str | None = None
    parent_id: str | None
    sibling_group: str | None
    depth: int
    session_name: str
    cwd: str
    session_file: str | None = None
    product_role: str | None = None
    repo: str | None = None
    worktree_label: str | None = None


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


Frame = Annotated[
    RegisterFrame
    | RegisteredFrame
    | ErrorFrame
    | DispatchFrame
    | DispatchAckFrame
    | TelemetryFrame
    | ThreadReportFrame
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
    | UpdateWorkstreamAckFrame,
    Field(discriminator="type"),
]


_FRAME_ADAPTER = TypeAdapter(Frame)


def parse_frame(data: dict[str, Any]) -> Frame:
    """Parse an inbound dict into a protocol frame union."""

    return _FRAME_ADAPTER.validate_python(data)


def serialize_frame(frame: Frame) -> dict[str, Any]:
    """Serialize a frame model into JSON-compatible dict form."""

    return frame.model_dump(mode="json", exclude_unset=True)


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
    "TelemetryFrame",
    "ThreadReportFrame",
    "ThreadReportNode",
    "UpdateWorkstreamAckFrame",
    "UpdateWorkstreamFrame",
    "WaitFrame",
    "WaitResultFrame",
    "WaitResultItem",
    "parse_frame",
    "serialize_frame",
]
