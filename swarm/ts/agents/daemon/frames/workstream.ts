import type { PROTOCOL_VERSION } from "./version.ts";

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

export type WorkstreamAgentStatus = "attached" | "failed";

export interface AttachWorkstreamAgentFrame {
	type: "attach_workstream_agent";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	workstream: string;
	repo?: string | null;
	worktree_label?: string | null;
	status?: WorkstreamAgentStatus;
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
