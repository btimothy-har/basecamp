import type { ProtocolEnvelope } from "./version.ts";

export type SessionAgentMode = "analysis" | "planning" | "work" | "copilot";

export interface RegisterFrame extends ProtocolEnvelope {
	type: "register";
	role: "agent" | "worker";
	node_id: string;
	agent_handle?: string | null;
	parent_id: string | null;
	sibling_group: string | null;
	depth: number;
	session_name: string;
	cwd: string;
	session_file?: string | null;
	repo?: string | null;
	worktree_label?: string | null;
	branch?: string | null;
	model?: string | null;
	agent_mode?: SessionAgentMode | null;
}

export interface SessionMetadataFrame extends ProtocolEnvelope {
	type: "session_metadata";
	session_name: string;
	model: string | null;
	agent_mode: SessionAgentMode;
	repo: string | null;
	worktree_label: string | null;
	branch: string | null;
}

export interface RegisteredFrame extends ProtocolEnvelope {
	type: "registered";
	node_id: string;
	protocol: number;
}

export interface ErrorFrame extends ProtocolEnvelope {
	type: "error";
	code: string;
	message: string;
}
