import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame, PeerMessageDeliveryFrame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { formatPeerMessageDeliveryContent, handlePeerMessageDelivery } from "../daemon/delivery.ts";

function deliveryFrame(overrides: Partial<PeerMessageDeliveryFrame> = {}): PeerMessageDeliveryFrame {
	return {
		type: "peer_message_delivery",
		v: PROTOCOL_VERSION,
		message_id: "message-1",
		from_handle: "worker-1",
		from_relation: "peer",
		message: "Please review the latest patch.",
		interrupt: false,
		...overrides,
	};
}

function createMockConnection(): { sent: Frame[]; send: (frame: Frame) => void } {
	const sent: Frame[] = [];
	return {
		sent,
		send(frame: Frame) {
			sent.push(frame);
		},
	};
}

describe("peer message delivery", () => {
	it("schedules interrupt deliveries as steer with concise sender context", () => {
		const calls: Array<{ content: string; deliverAs: string }> = [];
		const pi = {
			sendUserMessage(content: string, options: { deliverAs: "steer" | "followUp" }): Promise<void> {
				calls.push({ content, deliverAs: options.deliverAs });
				return Promise.resolve();
			},
		};
		const connection = createMockConnection();

		handlePeerMessageDelivery(pi, connection, deliveryFrame({ interrupt: true }));

		assert.deepEqual(calls, [
			{
				content: "Message from worker-1 (peer):\n\nPlease review the latest patch.",
				deliverAs: "steer",
			},
		]);
		assert.deepEqual(connection.sent, [
			{
				type: "peer_message_delivery_ack",
				v: PROTOCOL_VERSION,
				message_id: "message-1",
				status: "queued",
			},
		]);
	});

	it("schedules non-interrupt deliveries as followUp and queues ack immediately", () => {
		const calls: Array<{ content: string; deliverAs: string }> = [];
		const neverResolves = new Promise<void>(() => {
			// Intentionally pending to verify ack does not wait for a full turn.
		});
		const pi = {
			sendUserMessage(content: string, options: { deliverAs: "steer" | "followUp" }): Promise<void> {
				calls.push({ content, deliverAs: options.deliverAs });
				return neverResolves;
			},
		};
		const connection = createMockConnection();

		handlePeerMessageDelivery(pi, connection, deliveryFrame({ interrupt: false, message_id: "message-2" }));

		assert.deepEqual(calls, [
			{
				content: "Message from worker-1 (peer):\n\nPlease review the latest patch.",
				deliverAs: "followUp",
			},
		]);
		assert.deepEqual(connection.sent, [
			{
				type: "peer_message_delivery_ack",
				v: PROTOCOL_VERSION,
				message_id: "message-2",
				status: "queued",
			},
		]);
	});

	it("formats product role ahead of structural relation", () => {
		const content = formatPeerMessageDeliveryContent(
			deliveryFrame({
				from_handle: "clear-falcon-80cda5",
				from_relation: "unknown",
				from_product_role: "copilot",
				message: "Can you check this?",
			}),
		);

		assert.equal(content, "Message from clear-falcon-80cda5 (copilot):\n\nCan you check this?");
	});

	it("formats parent senders with canonical handle and relation when product role is absent", () => {
		const content = formatPeerMessageDeliveryContent(
			deliveryFrame({ from_handle: "quiet-badger-3dc450", from_relation: "parent", message: "Can you check this?" }),
		);

		assert.equal(content, "Message from quiet-badger-3dc450 (parent):\n\nCan you check this?");
	});

	it("does not convert queued ack transport errors into failed delivery", () => {
		const calls: Array<{ content: string; deliverAs: string }> = [];
		const pi = {
			sendUserMessage(content: string, options: { deliverAs: "steer" | "followUp" }): Promise<void> {
				calls.push({ content, deliverAs: options.deliverAs });
				return Promise.resolve();
			},
		};
		const connection = {
			send(_frame: Frame): void {
				throw new Error("socket closed");
			},
		};

		assert.doesNotThrow(() => handlePeerMessageDelivery(pi, connection, deliveryFrame({ message_id: "message-ack" })));
		assert.equal(calls.length, 1);
	});

	it("sends failed ack when sendUserMessage throws synchronously", () => {
		const pi = {
			sendUserMessage(): Promise<void> {
				throw new Error("Pi delivery unavailable");
			},
		};
		const connection = createMockConnection();

		handlePeerMessageDelivery(pi, connection, deliveryFrame({ message_id: "message-3" }));

		assert.deepEqual(connection.sent, [
			{
				type: "peer_message_delivery_ack",
				v: PROTOCOL_VERSION,
				message_id: "message-3",
				status: "failed",
				error: "Pi delivery unavailable",
			},
		]);
	});

	it("uses a neutral sender label and does not add private ids to formatted content", () => {
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorRunId = process.env.BASECAMP_RUN_ID;
		try {
			process.env.BASECAMP_AGENT_ID = "agent-private";
			process.env.BASECAMP_RUN_ID = "run-private";
			const content = formatPeerMessageDeliveryContent(deliveryFrame({ from_handle: null, from_relation: "unknown" }));

			assert.match(content, /^Message from a peer:/);
			assert.equal(content.includes("(unknown)"), false);
			assert.equal(content.includes("from_handle"), false);
			assert.equal(content.includes("message_id"), false);
			assert.equal(content.includes("agent-private"), false);
			assert.equal(content.includes("run-private"), false);
		} finally {
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorRunId === undefined) delete process.env.BASECAMP_RUN_ID;
			else process.env.BASECAMP_RUN_ID = priorRunId;
		}
	});
});
