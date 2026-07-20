import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { errorMessage } from "../../errors.ts";
import { type DaemonConnection, sanitizeDisplayLabel } from "../../hub/index.ts";
import type { PeerMessageDeliveryFrame } from "../../hub/protocol/index.ts";

/** The slice of the daemon-client state that peer-message delivery owns. */
export interface PeerDeliveryState {
	peerDeliveryConnection?: DaemonConnection | null;
	peerDeliveryUnsubscribe?: (() => void) | null;
}

export function formatPeerMessageDeliveryContent(frame: PeerMessageDeliveryFrame): string {
	const sender = sanitizeDisplayLabel(frame.from_handle, 80) ?? "a peer";
	const label = sanitizeDisplayLabel(frame.from_product_role, 48) ?? relationDisplayLabel(frame.from_relation);
	const suffix = label ? ` (${label})` : "";
	return `Message from ${sender}${suffix}:\n\n${frame.message}`;
}

function relationDisplayLabel(relation: PeerMessageDeliveryFrame["from_relation"]): string | null {
	return relation === "unknown" ? null : relation;
}

export function handlePeerMessageDelivery(
	pi: Pick<ExtensionAPI, "sendUserMessage">,
	connection: Pick<DaemonConnection, "send">,
	frame: PeerMessageDeliveryFrame,
): void {
	const deliverAs = frame.interrupt ? "steer" : "followUp";
	let delivery: ReturnType<ExtensionAPI["sendUserMessage"]>;
	try {
		delivery = pi.sendUserMessage(formatPeerMessageDeliveryContent(frame), { deliverAs });
	} catch (error) {
		try {
			connection.send({
				type: "peer_message_delivery_ack",
				message_id: frame.message_id,
				status: "failed",
				error: errorMessage(error),
			});
		} catch {
			// Transport failure prevents reporting the failed scheduling attempt; delivery status should not be inferred here.
		}
		return;
	}

	try {
		connection.send({
			type: "peer_message_delivery_ack",
			message_id: frame.message_id,
			status: "queued",
		});
	} catch {
		// sendUserMessage already accepted the delivery; do not convert an ack transport failure into delivery failure.
	}
	void Promise.resolve(delivery).catch(() => {
		// Delivery has already been accepted by Pi; avoid unhandled rejections without overwriting queued status.
	});
}

export function registerPeerMessageDeliveryHandler(
	pi: Pick<ExtensionAPI, "sendUserMessage">,
	state: PeerDeliveryState,
	connection: DaemonConnection,
): void {
	state.peerDeliveryUnsubscribe?.();
	state.peerDeliveryUnsubscribe = connection.on("peer_message_delivery", (frame) => {
		handlePeerMessageDelivery(pi, connection, frame);
	});
	state.peerDeliveryConnection = connection;
	connection.onClose(() => {
		if (state.peerDeliveryConnection === connection) {
			state.peerDeliveryUnsubscribe = null;
			state.peerDeliveryConnection = null;
		}
	});
}
