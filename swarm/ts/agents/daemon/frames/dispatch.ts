import type { PROTOCOL_VERSION } from "./version.ts";

export interface DispatchFrame {
	type: "dispatch";
	v: typeof PROTOCOL_VERSION;
	run_id: string;
	agent_id?: string;
	agent_handle?: string | null;
	agent_type?: string | null;
	run_kind?: string | null;
	model?: string | null;
	spec: {
		argv: string[];
		env: Record<string, string>;
		cwd: string;
		resume_path: string | null;
		fork_from?: string | null;
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
