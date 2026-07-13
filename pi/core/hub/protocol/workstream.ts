import type { ProtocolEnvelope } from "./version.ts";

export interface CreateWorkstreamFrame extends ProtocolEnvelope {
	type: "create_workstream";
	request_id: string;
	workstream_id: string;
	slug: string;
	label: string;
	brief: string;
	source_dossier_path: string;
	constraints?: string | null;
	source_repo_page_path?: string | null;
}

export interface CreateWorkstreamAckFrame extends ProtocolEnvelope {
	type: "create_workstream_ack";
	request_id: string;
	status: "created" | "slug_conflict" | "error";
	workstream_id?: string | null;
	slug?: string | null;
	error?: string | null;
}

export type WorkstreamAgentStatus = "attached" | "failed";

export interface AttachWorkstreamAgentFrame extends ProtocolEnvelope {
	type: "attach_workstream_agent";
	request_id: string;
	workstream: string;
	repo?: string | null;
	worktree_label?: string | null;
	status?: WorkstreamAgentStatus;
	error?: string | null;
}

export interface AttachWorkstreamAgentAckFrame extends ProtocolEnvelope {
	type: "attach_workstream_agent_ack";
	request_id: string;
	status: "attached" | "not_found" | "error";
	error?: string | null;
}

export interface UpdateWorkstreamFrame extends ProtocolEnvelope {
	type: "update_workstream";
	request_id: string;
	workstream: string;
	status: "open" | "closed";
}

export interface UpdateWorkstreamAckFrame extends ProtocolEnvelope {
	type: "update_workstream_ack";
	request_id: string;
	status: "updated" | "not_found" | "invalid_status" | "error";
	error?: string | null;
}

export interface ReviseWorkstreamFrame extends ProtocolEnvelope {
	type: "revise_workstream";
	request_id: string;
	workstream: string;
	label: string;
	brief: string;
	constraints?: string | null;
}

export interface ReviseWorkstreamAckFrame extends ProtocolEnvelope {
	type: "revise_workstream_ack";
	request_id: string;
	status: "revised" | "not_found" | "error";
	version?: number | null;
	error?: string | null;
}
