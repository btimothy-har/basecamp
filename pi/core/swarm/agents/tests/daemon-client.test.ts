import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { connect } from "../../../hub/index.ts";
import type { Frame } from "../../../hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "../../../hub/protocol/index.ts";
import { createDaemonClient } from "../client.ts";
import { MockConnection } from "./harness.ts";

class FakeWebSocket {
	sent: string[] = [];
	private handlers = new Map<string, Set<(...args: any[]) => void>>();

	on(event: string, handler: (...args: any[]) => void): void {
		const set = this.handlers.get(event) ?? new Set();
		set.add(handler);
		this.handlers.set(event, set);
	}

	send(payload: string): void {
		this.sent.push(payload);
	}

	close(): void {}

	emit(event: string, ...args: any[]): void {
		for (const handler of this.handlers.get(event) ?? []) handler(...args);
	}
}

describe("daemon client", () => {
	it("connect includes the canonical agent handle in the register frame", async () => {
		const socket = new FakeWebSocket();
		const connectionPromise = connect(
			{
				node_id: "node-1",
				agent_handle: "quiet-badger-3dc450",
				role: "agent",
				parent_id: null,
				sibling_group: null,
				depth: 0,
				session_name: "Root Session",
				cwd: "/repo",
			},
			{ socketPath: "/tmp/basecamp-test.sock", webSocketFactory: () => socket as any },
		);

		socket.emit("open");
		const register = JSON.parse(socket.sent[0] ?? "{}") as Extract<Frame, { type: "register" }>;
		assert.equal(register.type, "register");
		assert.equal(register.node_id, "node-1");
		assert.equal(register.agent_handle, "quiet-badger-3dc450");
		assert.equal(register.session_file, null);

		socket.emit(
			"message",
			JSON.stringify({ type: "registered", v: PROTOCOL_VERSION, node_id: "node-1", protocol: PROTOCOL_VERSION }),
		);
		const connection = await connectionPromise;
		connection.close();
	});

	it("connect includes session metadata in the register frame", async () => {
		const socket = new FakeWebSocket();
		const connectionPromise = connect(
			{
				node_id: "node-1",
				agent_handle: "quiet-badger-3dc450",
				role: "agent",
				parent_id: null,
				sibling_group: null,
				depth: 0,
				session_name: "Root Session",
				cwd: "/repo",
				session_file: "/tmp/pi-session.jsonl",
				repo: "acme/widgets",
				worktree_label: "copilot/brave-otter-quill",
			},
			{ socketPath: "/tmp/basecamp-test.sock", webSocketFactory: () => socket as any },
		);

		socket.emit("open");
		const register = JSON.parse(socket.sent[0] ?? "{}") as Extract<Frame, { type: "register" }>;
		assert.equal(register.type, "register");
		assert.equal(register.session_file, "/tmp/pi-session.jsonl");
		assert.equal(register.repo, "acme/widgets");
		assert.equal(register.worktree_label, "copilot/brave-otter-quill");

		socket.emit(
			"message",
			JSON.stringify({ type: "registered", v: PROTOCOL_VERSION, node_id: "node-1", protocol: PROTOCOL_VERSION }),
		);
		const connection = await connectionPromise;
		connection.close();
	});

	it("sendPeerMessage sends peer_message with a request id and waits only for matching ack", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.sendPeerMessage({ targetHandle: "target-agent", message: "hello", interrupt: true });
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		assert.equal(outbound.type, "peer_message");
		assert.equal(outbound.v, PROTOCOL_VERSION);
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.target_handle, "target-agent");
		assert.equal(outbound.message, "hello");
		assert.equal(outbound.interrupt, true);

		let resolved = false;
		promise.then(() => {
			resolved = true;
		});

		connection.emit({
			type: "peer_message_delivery",
			v: PROTOCOL_VERSION,
			message_id: "message-1",
			from_handle: "sender",
			from_relation: "peer",
			message: "delivery should not resolve sender",
			interrupt: false,
		});
		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: "different-request",
			message_id: "wrong-message",
			status: "accepted",
			error: null,
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(resolved, false);

		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-accepted",
			status: "accepted",
			error: null,
		});

		assert.deepEqual(await promise, { message_id: "message-accepted", status: "accepted", error: null });
	});

	it("cancelAgent sends cancel with a request id and waits only for matching ack", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.cancelAgent({ targetHandle: "target-agent" });
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "cancel" }>;
		assert.equal(outbound.type, "cancel");
		assert.equal(outbound.v, PROTOCOL_VERSION);
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.target_handle, "target-agent");

		let resolved = false;
		promise.then(() => {
			resolved = true;
		});

		connection.emit({
			type: "cancel_ack",
			v: PROTOCOL_VERSION,
			request_id: "different-request",
			status: "not_found",
			error: "wrong target",
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(resolved, false);

		connection.emit({
			type: "cancel_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			status: "cancelled",
			error: null,
		});

		assert.deepEqual(await promise, { status: "cancelled", error: null });
	});

	it("messageStatus sends message_status with wait and timeout options", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const promise = client.messageStatus({ messageId: "message-1", waitUntilDelivery: true, timeoutS: 7 });
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
		assert.equal(outbound.type, "message_status");
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.message_id, "message-1");
		assert.equal(outbound.wait_until_delivery, true);
		assert.equal(outbound.timeout_s, 7);

		let resolved = false;
		promise.then(() => {
			resolved = true;
		});
		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: "different-request",
			message_id: "message-1",
			status: "failed",
			error: "wrong",
			created_at: null,
			sent_at: null,
			queued_at: null,
			failed_at: null,
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(resolved, false);

		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-1",
			status: "queued",
			error: null,
			created_at: "2026-01-01T00:00:00Z",
			sent_at: "2026-01-01T00:00:01Z",
			queued_at: "2026-01-01T00:00:02Z",
			failed_at: null,
		});

		assert.deepEqual(await promise, {
			message_id: "message-1",
			status: "queued",
			error: null,
			created_at: "2026-01-01T00:00:00Z",
			sent_at: "2026-01-01T00:00:01Z",
			queued_at: "2026-01-01T00:00:02Z",
			failed_at: null,
		});
	});

	it("messageStatus correlates concurrent requests by request id", async () => {
		const connection = new MockConnection();
		const client = createDaemonClient(connection);

		const first = client.messageStatus({ messageId: "message-1" });
		const second = client.messageStatus({ messageId: "message-1" });
		await new Promise((resolve) => setImmediate(resolve));

		const firstOutbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
		const secondOutbound = connection.sent[1] as Extract<Frame, { type: "message_status" }>;
		assert.notEqual(firstOutbound.request_id, secondOutbound.request_id);

		let firstResolved = false;
		let secondResolved = false;
		first.then(() => {
			firstResolved = true;
		});
		second.then(() => {
			secondResolved = true;
		});

		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: secondOutbound.request_id,
			message_id: "message-1",
			status: "queued",
			error: null,
			created_at: null,
			sent_at: null,
			queued_at: "2026-01-01T00:00:02Z",
			failed_at: null,
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(firstResolved, false);
		assert.equal(secondResolved, true);
		assert.equal((await second).status, "queued");

		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: firstOutbound.request_id,
			message_id: "message-1",
			status: "sent",
			error: null,
			created_at: null,
			sent_at: "2026-01-01T00:00:01Z",
			queued_at: null,
			failed_at: null,
		});

		assert.equal((await first).status, "sent");
	});
});
