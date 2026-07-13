import type { ProtocolEnvelope } from "./version.ts";

export interface DispatchFrame extends ProtocolEnvelope {
	type: "dispatch";
	run_id: string;
	agent_id?: string;
	agent_handle?: string | null;
	agent_type?: string | null;
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

export interface DispatchAckFrame extends ProtocolEnvelope {
	type: "dispatch_ack";
	run_id: string;
	status: "spawned" | "rejected";
	reason: string | null;
}
