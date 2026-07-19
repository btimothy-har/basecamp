import type { ProtocolEnvelope } from "./version.ts";

export interface WaitFrame extends ProtocolEnvelope {
	type: "wait";
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

export interface WaitResultFrame extends ProtocolEnvelope {
	type: "wait_result";
	results: WaitResultItem[];
}
