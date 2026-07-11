import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ThreadReport } from "#swarm/index.ts";
import { registerThreadReporter } from "../thread-reporter.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<void> | void;

class MockPi {
	handlers = new Map<string, Handler[]>();
	on(event: string, handler: Handler): void {
		const existing = this.handlers.get(event) ?? [];
		existing.push(handler);
		this.handlers.set(event, existing);
	}
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

const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
const priorAgentId = process.env.BASECAMP_AGENT_ID;

afterEach(() => {
	if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
	else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
	if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
	else process.env.BASECAMP_AGENT_ID = priorAgentId;
});

describe("companion thread reporter", () => {
	it("maps getBranch() to per-entry nodes with session id + transcript path", async () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		delete process.env.BASECAMP_AGENT_ID;
		const reports: ThreadReport[] = [];
		const pi = new MockPi();
		registerThreadReporter(pi as never, async (build) => {
			reports.push(build());
		});

		const branch = [
			{ id: "e1", parentId: null, type: "message" },
			{ id: "e2", parentId: "e1", type: "message" },
		];
		await fireAgentEnd(pi, mockCtx(branch, { leafId: "e2", sessionId: "pi-sess", sessionFile: "/x/pi-sess.jsonl" }));

		assert.equal(reports.length, 1);
		const report = reports[0];
		assert.ok(report);
		assert.equal(report.node_id, "pi-sess");
		assert.equal(report.session_id, "pi-sess");
		assert.equal(report.session_file, "/x/pi-sess.jsonl");
		assert.equal(report.leaf_id, "e2");
		assert.deepEqual(report.nodes, [
			{ id: "e1", parent_id: null, entry_json: JSON.stringify(branch[0]) },
			{ id: "e2", parent_id: "e1", entry_json: JSON.stringify(branch[1]) },
		]);
	});

	it("prefers BASECAMP_AGENT_ID for node_id", async () => {
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.BASECAMP_AGENT_ID = "agent-xyz";
		const reports: ThreadReport[] = [];
		const pi = new MockPi();
		registerThreadReporter(pi as never, async (build) => {
			reports.push(build());
		});

		await fireAgentEnd(pi, mockCtx([], { leafId: null, sessionId: "pi-sess", sessionFile: null }));

		assert.equal(reports[0]?.node_id, "agent-xyz");
		assert.equal(reports[0]?.session_id, "pi-sess");
	});

	it("does not register for a subagent (agentDepth > 0)", () => {
		process.env.BASECAMP_AGENT_DEPTH = "1";
		const pi = new MockPi();
		registerThreadReporter(pi as never, async () => {});
		assert.equal(pi.handlers.get("agent_end"), undefined);
	});
});
