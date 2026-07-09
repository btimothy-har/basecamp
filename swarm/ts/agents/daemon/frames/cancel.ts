import type { PROTOCOL_VERSION } from "./version.ts";

export interface CancelFrame {
	type: "cancel";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	target_handle: string;
}

export interface CancelAckFrame {
	type: "cancel_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	status: "cancelled" | "not_found" | "not_authorized" | "already_terminal";
	error?: string | null;
}
