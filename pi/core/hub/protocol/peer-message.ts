import type { ProtocolEnvelope } from "./version.ts";

export interface PeerMessageFrame extends ProtocolEnvelope {
	type: "peer_message";
	request_id: string;
	target_handle: string;
	message: string;
	interrupt?: boolean;
}

export interface PeerMessageAckFrame extends ProtocolEnvelope {
	type: "peer_message_ack";
	request_id: string;
	message_id: string | null;
	status: "accepted" | "unknown";
	error?: string | null;
}

export type PeerMessageRelation = "self" | "parent" | "ancestor" | "child" | "descendant" | "peer" | "unknown";

export interface PeerMessageDeliveryFrame extends ProtocolEnvelope {
	type: "peer_message_delivery";
	message_id: string;
	from_handle: string | null;
	from_relation: PeerMessageRelation;
	from_product_role?: string | null;
	message: string;
	interrupt: boolean;
}

export interface PeerMessageDeliveryAckFrame extends ProtocolEnvelope {
	type: "peer_message_delivery_ack";
	message_id: string;
	status: "queued" | "failed";
	error?: string | null;
}
