import type { PROTOCOL_VERSION } from "./version.ts";

export interface MessageStatusFrame {
	type: "message_status";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string;
	wait_until_delivery?: boolean;
	timeout_s?: number;
}

export interface MessageStatusResultFrame {
	type: "message_status_result";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string;
	status: "accepted" | "sent" | "queued" | "failed" | "unavailable" | "unknown";
	error?: string | null;
	created_at: string | null;
	sent_at: string | null;
	queued_at: string | null;
	failed_at: string | null;
}
