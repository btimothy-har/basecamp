/**
 * Daemon wire protocol: one file per frame family, composed here. Core-owned
 * (core/hub is the hub-daemon adapter); swarm and companion consume it.
 * The Frame union, FRAME_TYPES, and the codec must stay in lockstep with the
 * Python side (src/basecamp/hub/frames/) — tests/frames.test.ts asserts
 * PROTOCOL_VERSION parity and round-trips the shared fixtures in
 * core/hub/protocol/frames/.
 */

import { Buffer } from "node:buffer";
import type { CancelAckFrame, CancelFrame } from "./cancel.ts";
import type { DispatchAckFrame, DispatchFrame } from "./dispatch.ts";
import type { ListAgentsFrame, ListAgentsResultFrame } from "./list-agents.ts";
import type { MessageStatusFrame, MessageStatusResultFrame } from "./message-status.ts";
import type {
	PeerMessageAckFrame,
	PeerMessageDeliveryAckFrame,
	PeerMessageDeliveryFrame,
	PeerMessageFrame,
} from "./peer-message.ts";
import type { ErrorFrame, RegisteredFrame, RegisterFrame } from "./register.ts";
import type { ResultReportFrame, TelemetryFrame } from "./telemetry.ts";
import type { ThreadReportFrame } from "./thread-report.ts";
import { PROTOCOL_VERSION } from "./version.ts";
import type { WaitFrame, WaitResultFrame } from "./wait.ts";
import type {
	AttachWorkstreamAgentAckFrame,
	AttachWorkstreamAgentFrame,
	CreateWorkstreamAckFrame,
	CreateWorkstreamFrame,
	UpdateWorkstreamAckFrame,
	UpdateWorkstreamFrame,
} from "./workstream.ts";

export type * from "./cancel.ts";
export type * from "./dispatch.ts";
export type * from "./list-agents.ts";
export type * from "./message-status.ts";
export type * from "./peer-message.ts";
export type * from "./register.ts";
export type * from "./telemetry.ts";
export type * from "./thread-report.ts";
export type * from "./wait.ts";
export type * from "./workstream.ts";
export { PROTOCOL_VERSION };

export type Frame =
	| RegisterFrame
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
	| UpdateWorkstreamAckFrame;

export const FRAME_TYPES = [
	"register",
	"registered",
	"error",
	"dispatch",
	"dispatch_ack",
	"telemetry",
	"thread_report",
	"result_report",
	"wait",
	"wait_result",
	"list_agents",
	"list_agents_result",
	"peer_message",
	"peer_message_ack",
	"peer_message_delivery",
	"peer_message_delivery_ack",
	"message_status",
	"message_status_result",
	"cancel",
	"cancel_ack",
	"create_workstream",
	"create_workstream_ack",
	"attach_workstream_agent",
	"attach_workstream_agent_ack",
	"update_workstream",
	"update_workstream_ack",
] as const;

const KNOWN_TYPE_SET = new Set<string>(FRAME_TYPES);

export function encodeFrame(frame: Frame): string {
	return JSON.stringify(frame);
}

export function decodeFrame(raw: string | Buffer): Frame {
	const text = Buffer.isBuffer(raw) ? raw.toString("utf8") : raw;
	const parsed: unknown = JSON.parse(text);

	if (!parsed || typeof parsed !== "object") {
		throw new Error("Invalid frame: expected object");
	}

	const record = parsed as Record<string, unknown>;
	if (typeof record.type !== "string" || !KNOWN_TYPE_SET.has(record.type)) {
		throw new Error(`Unknown frame type: ${String(record.type)}`);
	}
	if (record.v !== PROTOCOL_VERSION) {
		throw new Error(`Protocol version mismatch: got ${String(record.v)}, expected ${PROTOCOL_VERSION}`);
	}

	return record as unknown as Frame;
}
