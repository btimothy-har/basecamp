import type { PROTOCOL_VERSION } from "./version.ts";

export interface PeerMessageFrame {
	type: "peer_message";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	target_handle: string;
	message: string;
	interrupt?: boolean;
}

export interface PeerMessageAckFrame {
	type: "peer_message_ack";
	v: typeof PROTOCOL_VERSION;
	request_id: string;
	message_id: string | null;
	status: "accepted" | "unknown";
	error?: string | null;
}

export type PeerMessageRelation = "self" | "parent" | "ancestor" | "child" | "descendant" | "peer" | "unknown";

export interface PeerMessageDeliveryFrame {
	type: "peer_message_delivery";
	v: typeof PROTOCOL_VERSION;
	message_id: string;
	from_handle: string | null;
	from_relation: PeerMessageRelation;
	from_product_role?: string | null;
	message: string;
	interrupt: boolean;
}

export interface PeerMessageDeliveryAckFrame {
	type: "peer_message_delivery_ack";
	v: typeof PROTOCOL_VERSION;
	message_id: string;
	status: "queued" | "failed";
	error?: string | null;
}
