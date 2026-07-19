import type { ProtocolEnvelope } from "./version.ts";

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
