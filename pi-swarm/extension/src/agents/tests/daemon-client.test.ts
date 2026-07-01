import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	buildRunSummaryPath,
	connect,
	createDaemonClient,
	type DaemonConnection,
	parseRunSummaryResponse,
} from "../daemon/client.ts";
import type { Frame } from "../daemon/frames.ts";
import { PROTOCOL_VERSION } from "../daemon/frames.ts";

class MockConnection implements DaemonConnection {
	sent: Frame[] = [];
	handlers = new Map<Frame["type"], Set<(frame: any) => void>>();
	closeHandlers = new Set<(code: number, reason: string) => void>();

	send(frame: Frame): void {
		this.sent.push(frame);
	}

	on<T extends Frame["type"]>(type: T, handler: (frame: Extract<Frame, { type: T }>) => void): () => void {
		const set = this.handlers.get(type) ?? new Set();
		set.add(handler as any);
		this.handlers.set(type, set);
		return () => set.delete(handler as any);
	}

	onClose(handler: (code: number, reason: string) => void): () => void {
		this.closeHandlers.add(handler);
		return () => this.closeHandlers.delete(handler);
	}

	close(): void {}

	emit(frame: Frame): void {
		const set = this.handlers.get(frame.type);
		if (!set) return;
		for (const handler of set) handler(frame as any);
	}
}

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
				role: "session",
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

		socket.emit(
			"message",
			JSON.stringify({ type: "registered", v: PROTOCOL_VERSION, node_id: "node-1", protocol: PROTOCOL_VERSION }),
		);
		const connection = await connectionPromise;
		connection.close();
	});

	it("encodes root_id and clamps limits in the summary path", () => {
		assert.equal(
			buildRunSummaryPath("root id/with?chars", 500),
			"/runs/summary?root_id=root%20id%2Fwith%3Fchars&limit=50",
		);
		assert.equal(buildRunSummaryPath("root", -12), "/runs/summary?root_id=root&limit=0");
		assert.equal(buildRunSummaryPath("root", 4.8), "/runs/summary?root_id=root&limit=4");
	});

	it("parses valid agent task detail and ignores malformed rows", () => {
		const result = parseRunSummaryResponse({
			root_id: "root",
			session_active: true,
			agents: [
				"bad",
				{ agent_handle: 123, session_name: "bad", status: "running" },
				{
					agent_handle: "worker-1",
					agent_id_short: "abc123ef",
					agent_type: "worker",
					model: "anthropic/claude-sonnet",
					session_name: "worker",
					status: "running",
					created_at: "2026-01-01T00:00:00Z",
					started_at: "2026-01-01T00:00:01Z",
					ended_at: null,
					recent_activity: [
						"bad",
						{ kind: "tool_call", seq: 1, timestamp: "2026-01-01T00:00:02Z", label: "read", snippet: "read file" },
						{
							kind: "tool_result",
							seq: 2,
							timestamp: "2026-01-01T00:00:03Z",
							category: "tool",
							label: "read",
							snippet: "ok",
							toolName: "read",
							isError: false,
							turnIndex: "bad",
							toolCallId: "hidden",
						},
					],
					task: {
						goal: "Build the thing",
						task_plan: [
							{ index: 0, label: "Done", status: "completed" },
							"bad",
							{ index: 1, label: "Now", status: "active" },
						],
						current_task: { index: 1, label: "Now", status: "active", notes: "ignored" },
					},
					latest_message: "not part of the TS summary surface",
				},
			],
		});

		assert.ok(result);
		assert.equal(result.root_id, "root");
		assert.equal(result.session_active, true);
		assert.equal(result.agents.length, 1);
		const [agent] = result.agents;
		assert.equal(agent?.agent_handle, "worker-1");
		assert.equal(agent?.agent_id_short, "abc123ef");
		assert.equal(agent?.model, "anthropic/claude-sonnet");
		assert.deepEqual(agent?.recent_activity, [
			{
				kind: "tool_call",
				seq: 1,
				timestamp: "2026-01-01T00:00:02Z",
				category: null,
				label: "read",
				snippet: "read file",
				toolName: null,
				isError: null,
				turnIndex: null,
				toolCount: null,
			},
			{
				kind: "tool_result",
				seq: 2,
				timestamp: "2026-01-01T00:00:03Z",
				category: "tool",
				label: "read",
				snippet: "ok",
				toolName: "read",
				isError: false,
				turnIndex: null,
				toolCount: null,
			},
		]);
		assert.equal(JSON.stringify(agent?.recent_activity).includes("hidden"), false);
		assert.equal(agent?.task?.goal, "Build the thing");
		assert.deepEqual(
			agent?.task?.task_plan?.map((item) => item.label),
			["Done", "Now"],
		);
		assert.deepEqual(agent?.task?.current_task, { index: 1, label: "Now", status: "active" });
		assert.equal(Object.hasOwn(agent ?? {}, "latest_message"), false);
	});

	it("returns null for non-object summary payloads", () => {
		assert.equal(parseRunSummaryResponse(null), null);
		assert.equal(parseRunSummaryResponse("bad"), null);
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
