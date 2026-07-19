import type { ProtocolEnvelope } from "./version.ts";

export interface CancelFrame extends ProtocolEnvelope {
	type: "cancel";
	request_id: string;
	target_handle: string;
}

export interface CancelAckFrame extends ProtocolEnvelope {
	type: "cancel_ack";
	request_id: string;
	status: "cancelled" | "not_found" | "not_authorized" | "already_terminal";
	error?: string | null;
}
