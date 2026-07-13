import type { PROTOCOL_VERSION } from "./version.ts";

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
	repo?: string | null;
	worktree_label?: string | null;
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
