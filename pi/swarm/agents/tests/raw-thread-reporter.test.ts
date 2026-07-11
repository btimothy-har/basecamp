import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DaemonConnection } from "../daemon/client.ts";
import type { Frame } from "../daemon/frames/index.ts";
import { PROTOCOL_VERSION } from "../daemon/frames/index.ts";
import { registerRawThreadReporter } from "../daemon/raw-thread-reporter.ts";
import { MockPi } from "./harness.ts";

function mockConnection(sent: Frame[]): DaemonConnection {
	return {
		send(frame) {
			sent.push(frame);
		},
		on() {
			return () => {};
		},
		onClose() {
			return () => {};
		},
		close() {
			// no-op
		},
	};
}

function mockCtx(
	branch: { id: string; parentId: string | null }[],
	opts: { leafId: string | null; sessionId: string; sessionFile: string | null },
): unknown {
	return {
		sessionManager: {
			getSessionId: () => opts.sessionId,
			getLeafId: () => opts.leafId,
			getBranch: () => branch,
			getSessionFile: () => opts.sessionFile,
		},
	};
}

async function fireAgentEnd(pi: MockPi, ctx: unknown): Promise<void> {
	const handler = pi.handlers.get("agent_end")?.[0];
	assert.ok(handler, "agent_end handler registered");
	await handler({}, ctx);
}

describe("raw thread reporter", () => {
	it("ships getBranch() as per-entry nodes with session id + transcript path", async () => {
		const sent: Frame[] = [];
		const connection = mockConnection(sent);
		const pi = new MockPi();
		registerRawThreadReporter(pi as unknown as never, { awaitConnection: async () => connection });

		const branch = [
			{ id: "e1", parentId: null, type: "message" },
			{ id: "e2", parentId: "e1", type: "message" },
		];

		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		delete process.env.BASECAMP_AGENT_ID;
		try {
			await fireAgentEnd(pi, mockCtx(branch, { leafId: "e2", sessionId: "pi-sess", sessionFile: "/x/pi-sess.jsonl" }));
		} finally {
			if (priorAgentId !== undefined) process.env.BASECAMP_AGENT_ID = priorAgentId;
		}

		assert.equal(sent.length, 1);
		const frame = sent[0];
		if (frame?.type !== "thread_report") {
			assert.fail("expected a thread_report frame");
		}
		assert.equal(frame.v, PROTOCOL_VERSION);
		assert.equal(frame.node_id, "pi-sess");
		assert.equal(frame.session_id, "pi-sess");
		assert.equal(frame.session_file, "/x/pi-sess.jsonl");
		assert.equal(frame.leaf_id, "e2");
		assert.deepEqual(frame.nodes, [
			{ id: "e1", parent_id: null, entry_json: JSON.stringify(branch[0]) },
			{ id: "e2", parent_id: "e1", entry_json: JSON.stringify(branch[1]) },
		]);
	});

	it("carries a null transcript path and prefers BASECAMP_AGENT_ID for node_id", async () => {
		const sent: Frame[] = [];
		const connection = mockConnection(sent);
		const pi = new MockPi();
		registerRawThreadReporter(pi as unknown as never, { awaitConnection: async () => connection });

		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		process.env.BASECAMP_AGENT_ID = "agent-xyz";
		try {
			await fireAgentEnd(pi, mockCtx([], { leafId: null, sessionId: "pi-sess", sessionFile: null }));
		} finally {
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
		}

		const frame = sent[0];
		if (frame?.type !== "thread_report") {
			assert.fail("expected a thread_report frame");
		}
		assert.equal(frame.node_id, "agent-xyz");
		assert.equal(frame.session_id, "pi-sess");
		assert.equal(frame.session_file, null);
		assert.equal(frame.leaf_id, null);
		assert.deepEqual(frame.nodes, []);
	});

	it("sends over the current connection across a reconnect (fork → new owner)", async () => {
		const sentA: Frame[] = [];
		const sentB: Frame[] = [];
		const connA = mockConnection(sentA);
		const connB = mockConnection(sentB);
		let current: DaemonConnection = connA;
		const pi = new MockPi();
		registerRawThreadReporter(pi as unknown as never, { awaitConnection: async () => current });

		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		delete process.env.BASECAMP_AGENT_ID;
		try {
			await fireAgentEnd(
				pi,
				mockCtx([{ id: "a1", parentId: null }], { leafId: "a1", sessionId: "sess-A", sessionFile: null }),
			);
			// a /fork reconnects the daemon client under a new session id
			current = connB;
			await fireAgentEnd(
				pi,
				mockCtx([{ id: "b1", parentId: null }], { leafId: "b1", sessionId: "sess-B", sessionFile: null }),
			);
		} finally {
			if (priorAgentId !== undefined) process.env.BASECAMP_AGENT_ID = priorAgentId;
		}

		assert.equal(sentA.length, 1);
		assert.equal(sentB.length, 1);
		const frameA = sentA[0];
		const frameB = sentB[0];
		if (frameA?.type !== "thread_report" || frameB?.type !== "thread_report") {
			assert.fail("expected thread_report frames");
		}
		assert.equal(frameA.session_id, "sess-A");
		assert.equal(frameA.node_id, "sess-A");
		assert.equal(frameB.session_id, "sess-B");
		assert.equal(frameB.node_id, "sess-B");
	});
});
