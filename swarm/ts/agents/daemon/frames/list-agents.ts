import type { PROTOCOL_VERSION } from "./version.ts";

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
