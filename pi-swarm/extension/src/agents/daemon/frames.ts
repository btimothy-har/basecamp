import { Buffer } from "node:buffer";

// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
// v18: cancel-agent request/ack frames.
// v19: workstream create/attach/update frames + /workstreams HTTP reads.
export const PROTOCOL_VERSION = 19;

export interface RegisterFrame {
	type: "register";
	v: typeof PROTOCOL_VERSION;
	role: "session" | "agent";
	node_id: string;
	agent_handle?: string | null;
	parent_id: string | null;
	sibling_group: string | null;
	depth: number;
	session_name: string;
	cwd: string;
	session_file?: string | null;
	product_role?: string | null;
}

export interface RegisteredFrame {
	type: "registered";
	v: typeof PROTOCOL_VERSION;
	node_id: string;
	protocol: number;
}

export interface ErrorFrame {
	type: "error";
	v: typeof PROTOCOL_VERSION;
	code: string;
	message: string;
}

export interface DispatchFrame {
	type: "dispatch";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id?: string;
	agent_handle?: string | null;
	agent_type?: string | null;
	run_kind?: string | null;
	model?: string | null;
	spec: {
		argv: string[];
		env: Record<string, string>;
		cwd: string;
		resume_path: string | null;
		fork_from?: string | null;
		task: string;
	};
}

export interface DispatchAckFrame {
	type: "dispatch_ack";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	status: "spawned" | "rejected";
	reason: string | null;
}

export interface TelemetryFrame {
	type: "telemetry";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id: string;
	report_token: string;
	kind: string;
	payload: Record<string, unknown>;
}

export interface ResultReportFrame {
	type: "result_report";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id: string;
	report_token: string;
	status: "ok" | "error";
	result: string | null;
	error: string | null;
	usage: Record<string, unknown> | null;
}

export interface WaitFrame {
	type: "wait";
	v: typeof PROTOCOL_VERSION;
	agent_ids: string[];
	agent_handles?: string[];
	mode: "all";
	timeout_s: number;
}

export interface WaitResultItem {
	agent_id?: string | null;
	agent_handle?: string | null;
	status: "completed" | "failed" | "running" | "unknown";
	result: string | null;
	error: string | null;
}

export interface WaitResultFrame {
	type: "wait_result";
	v: typeof PROTOCOL_VERSION;
	results: WaitResultItem[];
}

export interface ListAgentsFrame {
	type: "list_agents";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	awaitable?: boolean;
}

export interface ListAgentItem {
	agent_id: string;
	agent_handle?: string | null;
	agent_type?: string | null;
	run_kind?: string | null;
	parent_id: string | null;
	role: string;
	session_name: string;
	depth: number;
	status: "pending" | "running" | "completed" | "failed" | "idle";
	awaitable: boolean;
	task?: string | null;
}

export interface ListAgentsResultFrame {
	type: "list_agents_result";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	agents: ListAgentItem[];
}

export interface PeerMessageFrame {
	type: "peer_message";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	target_handle: string;
	message: string;
	interrupt?: boolean;
}

export interface PeerMessageAckFrame {
	type: "peer_message_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string | null;
	status: "accepted" | "unknown";
	error?: string | null;
}

export type PeerMessageRelation = "self" | "parent" | "ancestor" | "child" | "descendant" | "peer" | "unknown";

export interface PeerMessageDeliveryFrame {
	type: "peer_message_delivery";
	v: typeof PROTOCOL_VERSION;
	message_id: string;
	from_handle: string | null;
	from_relation: PeerMessageRelation;
	from_product_role?: string | null;
	message: string;
	interrupt: boolean;
}

export interface PeerMessageDeliveryAckFrame {
	type: "peer_message_delivery_ack";
	v: typeof PROTOCOL_VERSION;
	message_id: string;
	status: "queued" | "failed";
	error?: string | null;
}

export interface MessageStatusFrame {
	type: "message_status";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string;
	wait_until_delivery?: boolean;
	timeout_s?: number;
}

export interface MessageStatusResultFrame {
	type: "message_status_result";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string;
	status: "accepted" | "sent" | "queued" | "failed" | "unavailable" | "unknown";
	error?: string | null;
	created_at: string | null;
	sent_at: string | null;
	queued_at: string | null;
	failed_at: string | null;
}

export interface CancelFrame {
	type: "cancel";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	target_handle: string;
}

export interface CancelAckFrame {
	type: "cancel_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	status: "cancelled" | "not_found" | "not_authorized" | "already_terminal";
	error?: string | null;
}

export interface CreateWorkstreamFrame {
	type: "create_workstream";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	workstream_id: string;
	slug: string;
	label: string;
	brief: string;
	source_dossier_path: string;
	constraints?: string | null;
	source_repo_page_path?: string | null;
}

export interface CreateWorkstreamAckFrame {
	type: "create_workstream_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	status: "created" | "slug_conflict" | "error";
	workstream_id?: string | null;
	slug?: string | null;
	error?: string | null;
}

export interface AttachWorkstreamAgentFrame {
	type: "attach_workstream_agent";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	workstream: string;
	repo?: string | null;
	worktree_label?: string | null;
	status?: string;
	error?: string | null;
}

export interface AttachWorkstreamAgentAckFrame {
	type: "attach_workstream_agent_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	status: "attached" | "not_found" | "error";
	error?: string | null;
}

export interface UpdateWorkstreamFrame {
	type: "update_workstream";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	workstream: string;
	status: "open" | "closed";
}

export interface UpdateWorkstreamAckFrame {
	type: "update_workstream_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	status: "updated" | "not_found" | "invalid_status" | "error";
	error?: string | null;
}

export type Frame =
	| RegisterFrame
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
	| UpdateWorkstreamAckFrame;

export const FRAME_TYPES = [
	"register",
	"registered",
	"error",
	"dispatch",
	"dispatch_ack",
	"telemetry",
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
