import type { ProtocolEnvelope } from "./version.ts";

export interface ListAgentsFrame extends ProtocolEnvelope {
	type: "list_agents";
	request_id: string;
	awaitable?: boolean;
}

export interface ListAgentItem {
	agent_id: string;
	agent_handle?: string | null;
	agent_type?: string | null;
	parent_id: string | null;
	role: string;
	session_name: string;
	depth: number;
	status: "pending" | "running" | "completed" | "failed" | "idle";
	awaitable: boolean;
	task?: string | null;
}

export interface ListAgentsResultFrame extends ProtocolEnvelope {
	type: "list_agents_result";
	request_id: string;
	agents: ListAgentItem[];
}
