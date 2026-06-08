import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DaemonConnection } from "../agents/daemon/client.ts";
import type { Frame } from "../agents/daemon/frames.ts";
import { registerDaemonTools } from "../agents/daemon/tools.ts";

interface RegisteredTool {
	name: string;
	execute: (id: string, params: any, signal: AbortSignal, onUpdate: () => void, ctx: any) => Promise<any>;
}

class MockConnection implements DaemonConnection {
	sent: Frame[] = [];
	handlers = new Map<Frame["type"], Set<(frame: any) => void>>();

	send(frame: Frame): void {
		this.sent.push(frame);
	}

	on<T extends Frame["type"]>(type: T, handler: (frame: Extract<Frame, { type: T }>) => void): () => void {
		const set = this.handlers.get(type) ?? new Set();
		set.add(handler as any);
		this.handlers.set(type, set);
		return () => set.delete(handler as any);
	}

	onClose(): () => void {
		return () => {};
	}

	close(): void {
		// no-op
	}

	emit(frame: Frame): void {
		const set = this.handlers.get(frame.type);
		if (!set) return;
		for (const handler of set) handler(frame as any);
	}
}

function createMockPi() {
	const tools: RegisteredTool[] = [];
	const pi = {
		registerTool(tool: RegisteredTool) {
			tools.push(tool);
		},
		getSessionName() {
			return "session-name";
		},
		getAllTools() {
			return [];
		},
	};
	return { pi: pi as any, tools };
}

function toolByName(tools: RegisteredTool[], name: string): RegisteredTool {
	const tool = tools.find((candidate) => candidate.name === name);
	assert.ok(tool, `Missing tool ${name}`);
	return tool;
}

describe("daemon async tools", () => {
	it("dispatch_agent builds spec env/task split and returns handle on spawned ack", async () => {
		const priorCustom = process.env.TEST_DAEMON_TOOLS;
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorProject = process.env.BASECAMP_PROJECT;
		process.env.TEST_DAEMON_TOOLS = "1";
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.BASECAMP_PROJECT = "proj";

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			registerDaemonTools(pi, async () => connection);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world" },
				new AbortController().signal,
				() => {},
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.type, "dispatch");
			assert.equal(outbound.spec.task, "Task: hello world");
			assert.notEqual(outbound.spec.argv.at(-1), "Task: hello world");
			assert.equal(outbound.spec.env.TEST_DAEMON_TOOLS, "1");
			assert.equal(outbound.spec.env.BASECAMP_PROJECT, "proj");
			assert.equal(outbound.spec.env.BASECAMP_PARENT_SESSION, process.env.BASECAMP_SESSION_NAME ?? "session-name");

			connection.emit({
				type: "dispatch_ack",
				v: 1,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});

			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.equal(result.details.runId, outbound.run_id);
		} finally {
			if (priorCustom === undefined) delete process.env.TEST_DAEMON_TOOLS;
			else process.env.TEST_DAEMON_TOOLS = priorCustom;
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorProject === undefined) delete process.env.BASECAMP_PROJECT;
			else process.env.BASECAMP_PROJECT = priorProject;
		}
	});

	it("dispatch_agent surfaces rejected ack reason as tool error", async () => {
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const executePromise = dispatchTool.execute("1", { task: "hello world" }, new AbortController().signal, () => {}, {
			model: "claude-sonnet",
			sessionManager: { getSessionId: () => "session-id" },
		});
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;

		connection.emit({
			type: "dispatch_ack",
			v: 1,
			run_id: outbound.run_id,
			status: "rejected",
			reason: "depth_cap",
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /depth_cap/);
	});

	it("wait_for_agent sends wait and returns per-handle results", async () => {
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection);
		const waitTool = toolByName(tools, "wait_for_agent");

		const executePromise = waitTool.execute(
			"1",
			{ handles: ["run-1", "run-2"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.run_ids, ["run-1", "run-2"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: 1,
			results: [
				{ run_id: "run-1", status: "completed", result: "done", error: null },
				{ run_id: "run-2", status: "failed", result: null, error: "boom" },
			],
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items[0].status, "completed");
		assert.equal(result.details.items[1].status, "failed");
	});

	it("wait_for_agent aborts promptly on AbortSignal", async () => {
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection);
		const waitTool = toolByName(tools, "wait_for_agent");

		const controller = new AbortController();
		const executePromise = waitTool.execute("1", { handles: "run-1", timeout_s: 30 }, controller.signal, () => {}, {});
		controller.abort();

		const result = await executePromise;
		assert.equal(result.details.aborted, true);
		assert.match(result.content[0].text, /wait aborted/i);
	});
});
