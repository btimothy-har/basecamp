import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { registerDaemonTools } from "#core/swarm/agents/tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("wait_for_agent", () => {
	installDaemonToolTestHooks();

	it("sends wait and returns per-handle results", async () => {
		const { connection, outbound, resultPromise } = await dispatchWait(["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"]);
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_ids, []);
		assert.deepEqual(outbound.agent_handles, ["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: "some-other-wait",
			results: [
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "duplicate", error: null },
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "duplicate", error: null },
			],
		});
		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			results: [
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "done", error: null },
				{
					agent_handle: "mossy-lynx-d4e5f6",
					status: "failed",
					result: "compensation skipped",
					error: "boom",
				},
			],
		});

		const result = await resultPromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items[0].status, "completed");
		assert.equal(result.details.items[1].status, "failed");
		assert.match(result.content[0].text, /done/);
		assert.match(result.content[0].text, /boom/);
		assert.match(result.content[0].text, /compensation skipped/);
	});

	it("maps running and unknown statuses", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");

		const executePromise = waitTool.execute(
			"1",
			{ handles: ["scout-running", "scout-missing", "scout-complete"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_ids, []);
		assert.deepEqual(outbound.agent_handles, ["scout-running", "scout-missing", "scout-complete"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			results: [
				{ agent_handle: "scout-running", status: "running", result: null, error: null },
				{ agent_handle: "scout-missing", status: "unknown", result: null, error: null },
				{ agent_handle: "scout-complete", status: "completed", result: "ok", error: null },
			],
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items[0].status, "running");
		assert.equal(result.details.items[1].status, "unknown");
		assert.equal(result.details.items[2].status, "completed");
		assert.match(result.content[0].text, /still running \(timed out\)/);
		assert.match(result.content[0].text, /\? scout-missing not awaitable or unavailable/);
	});

	it("parses a JSON-encoded handles string and maps per-handle results", async () => {
		// Regression: models sometimes emit the array as a JSON string; the whole blob
		// must not be treated as one handle ("not awaitable or unavailable" for all).
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");

		const executePromise = waitTool.execute(
			"1",
			{ handles: '["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"]', timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_handles, ["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"]);

		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			results: [
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "done", error: null },
				{ agent_handle: "mossy-lynx-d4e5f6", status: "completed", result: "also done", error: null },
			],
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items.length, 2);
		assert.equal(result.details.items[0].agentHandle, "amber-fox-a1b2c3");
		assert.equal(result.details.items[0].status, "completed");
		assert.equal(result.details.items[1].agentHandle, "mossy-lynx-d4e5f6");
		assert.match(result.content[0].text, /done/);
		assert.doesNotMatch(result.content[0].text, /not awaitable or unavailable/);
	});

	it("surfaces daemon error on unknown items carrying one", async () => {
		const { connection, outbound, resultPromise } = await dispatchWait(["jade-tiger-9z8y7x"]);
		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			results: [{ agent_handle: "jade-tiger-9z8y7x", status: "unknown", result: null, error: "boom" }],
		});
		const result = await resultPromise;
		assert.equal(result.details.items[0].status, "unknown");
		// The daemon sends the raw cause; the renderer adds the single "wait failed:" prefix.
		assert.equal(result.content[0].text, "? jade-tiger-9z8y7x wait failed: boom");
	});

	it("collapses and truncates a long multi-line wait error", async () => {
		const { connection, outbound, resultPromise } = await dispatchWait(["jade-tiger-9z8y7x"]);
		// A server exception can be long and multi-line (chained repr, embedded SQL).
		const longError = ` OperationalError:\n  database is locked\n  ${"x".repeat(120)}`;
		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			results: [{ agent_handle: "jade-tiger-9z8y7x", status: "unknown", result: null, error: longError }],
		});
		const result = await resultPromise;
		const line = result.content[0].text;
		assert.equal(result.details.items[0].status, "unknown");
		// One line per item: whitespace collapsed (no newlines), truncated to the preview cap.
		assert.doesNotMatch(line, /\n/);
		assert.match(line, /^\? jade-tiger-9z8y7x wait failed: .{0,80}…$/);
	});

	it("fails before daemon connection/send when agents skill has not been invoked", async () => {
		let connected = false;
		const { pi, tools } = createMockPi();
		registerDaemonTools(
			pi,
			async () => {
				connected = true;
				return new MockConnection();
			},
			daemonToolDeps,
		);
		const waitTool = toolByName(tools, "wait_for_agent");

		const result = await waitTool.execute(
			"1",
			{ agent_handles: ["amber-fox-a1b2c3"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);
		assert.equal(result.details, null);
	});

	it("aborts promptly on AbortSignal", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");

		const controller = new AbortController();
		const executePromise = waitTool.execute(
			"1",
			{ agent_handles: "amber-fox-a1b2c3", timeout_s: 30 },
			controller.signal,
			() => {},
			{},
		);
		controller.abort();

		const result = await executePromise;
		assert.equal(result.details.aborted, true);
		assert.match(result.content[0].text, /wait aborted/i);
	});

	async function dispatchWait(handles: string[]) {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");
		const resultPromise = waitTool.execute(
			"1",
			{ agent_handles: handles, timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		return { connection, outbound, resultPromise };
	}
});
