import { Buffer } from "node:buffer";

// Gates every client-visible daemon capability, not just WebSocket frame shapes.
// This includes HTTP endpoints like /runs/summary, so stale daemons restart.
export const PROTOCOL_VERSION = 3;

export interface RegisterFrame {
	type: "register";
	v: typeof PROTOCOL_VERSION;
	role: "session" | "agent";
	node_id: string;
	parent_id: string | null;
	sibling_group: string | null;
	depth: number;
	session_name: string;
	cwd: string;
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
	spec: {
		argv: string[];
		env: Record<string, string>;
		cwd: string;
		resume_path: string | null;
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
	mode: "all";
	timeout_s: number;
}

export interface WaitResultItem {
	agent_id: string;
	status: "completed" | "failed" | "running" | "unknown";
	result: string | null;
	error: string | null;
}

export interface WaitResultFrame {
	type: "wait_result";
	v: typeof PROTOCOL_VERSION;
	results: WaitResultItem[];
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
	| WaitResultFrame;

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
