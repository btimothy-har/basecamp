import type { PROTOCOL_VERSION } from "./version.ts";

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
