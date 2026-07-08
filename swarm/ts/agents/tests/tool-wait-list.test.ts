import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createDaemonClient } from "../daemon/client.ts";
import type { Frame, ListAgentItem } from "../daemon/frames/index.ts";
import { PROTOCOL_VERSION } from "../daemon/frames/index.ts";
import { registerDaemonTools } from "../daemon/tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("wait_for_agent and list_agents", () => {
	installDaemonToolTestHooks();

	it("wait_for_agent sends wait and returns per-handle results", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");

		const executePromise = waitTool.execute(
			"1",
			{ agent_handles: ["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_ids, []);
		assert.deepEqual(outbound.agent_handles, ["amber-fox-a1b2c3", "mossy-lynx-d4e5f6"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			results: [
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "duplicate", error: null },
				{ agent_handle: "amber-fox-a1b2c3", status: "completed", result: "duplicate", error: null },
			],
		});
		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
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

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items[0].status, "completed");
		assert.equal(result.details.items[1].status, "failed");
		assert.match(result.content[0].text, /done/);
		assert.match(result.content[0].text, /boom/);
		assert.match(result.content[0].text, /compensation skipped/);
	});

	it("wait_for_agent maps running and unknown statuses", async () => {
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

	it("wait_for_agent fails before daemon connection/send when agents skill has not been invoked", async () => {
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

	it("list_agents sends request, waits on request id, and formats response rows", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const listTool = toolByName(tools, "list_agents");

		const executePromise = listTool.execute("1", { awaitable: true }, new AbortController().signal, () => {}, {});
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "list_agents" }>;
		assert.equal(outbound.type, "list_agents");
		assert.equal(outbound.awaitable, true);
		assert.equal(typeof outbound.request_id, "string");

		const response = {
			type: "list_agents_result" as const,
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			agents: [
				{
					agent_id: "00000000-0000-4000-8000-000000000001",
					agent_handle: "amber-fox-a1b2c3",
					agent_type: "scout",
					parent_id: "session-1",
					role: "agent",
					session_name: "agent-one",
					depth: 1,
					status: "running",
					awaitable: true,
					task: "Retask functional check",
				},
				{
					agent_id: "00000000-0000-4000-8000-000000000002",
					agent_handle: "mossy-lynx-d4e5f6",
					agent_type: "testing-specialist",
					parent_id: "00000000-0000-4000-8000-000000000001",
					role: "agent",
					session_name: "agent-two",
					depth: 2,
					status: "completed",
					awaitable: false,
				},
				{
					agent_id: "00000000-0000-4000-8000-000000000003",
					agent_handle: "00000000-0000-4000-8000-000000000003",
					parent_id: "session-1",
					role: "agent",
					session_name: "private-fallback",
					depth: 1,
					status: "running",
					awaitable: true,
				},
				{
					agent_id: "00000000-0000-4000-8000-000000000004",
					agent_handle: "silver-wren-d4e5f6",
					agent_type: "scout",
					parent_id: "session-1",
					role: "agent",
					session_name: "silver-wren-d4e5f6",
					depth: 1,
					status: "idle",
					awaitable: false,
				},
			] as ListAgentItem[],
		} as Extract<Frame, { type: "list_agents_result" }>;
		connection.emit(response);

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agents.length, 3);
		assert.equal(result.details.agents[0].agentHandle, "amber-fox-a1b2c3");
		assert.equal(result.details.agents[0].agentType, "scout");
		assert.equal(result.details.agents[0].task, "Retask functional check");
		assert.equal("agent_id" in result.details.agents[0], false);
		assert.equal(result.details.agents[1].status, "completed");
		assert.equal(result.details.agents[2].agentHandle, "silver-wren-d4e5f6");
		assert.equal(result.details.agents[2].agentType, "scout");
		assert.equal(result.details.agents[2].sessionName, null);
		assert.match(result.content[0].text, /amber-fox-a1b2c3 \(scout\)/);
		assert.match(result.content[0].text, /task: Retask functional check/);
		assert.match(result.content[0].text, /mossy-lynx-d4e5f6 \(testing-specialist\)/);
		assert.doesNotMatch(result.content[0].text, /agent_id|run_id|spec_json|env_keys|SECRET/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000001/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000003/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000004/);
		assert.doesNotMatch(result.content[0].text, /private-fallback/);
		assert.match(result.content[0].text, /silver-wren-d4e5f6 \(scout\)/);
		assert.doesNotMatch(result.content[0].text, /title: silver-wren-d4e5f6/);
		assert.match(result.content[0].text, /title: agent-one/);
		assert.match(result.content[0].text, /title: agent-two/);
		assert.match(result.content[0].text, /running/);
		assert.match(result.content[0].text, /completed/);

		const rendered = (listTool as any)
			.renderResult(result, {}, { fg: (_token: string, text: string) => `styled:${text}` })
			.render(120)
			.join("\n");
		assert.match(rendered, /amber-fox-a1b2c3 \(scout\)/);
		assert.doesNotMatch(rendered, /amber-fox-a1b2c3 styled:amber-fox-a1b2c3/);
	});

	it("list_agents rejects when the daemon connection closes before a response", async () => {
		const connection = new MockConnection();
		const daemonClient = createDaemonClient(connection);
		const resultPromise = daemonClient.listAgents({ awaitable: true });
		const rejection = assert.rejects(
			resultPromise,
			/daemon connection closed before list_agents_result frame \(1006: gone\)/,
		);

		assert.equal(connection.sent[0]?.type, "list_agents");
		connection.emitClose(1006, "gone");

		await rejection;
		assert.equal(connection.handlers.get("list_agents_result")?.size ?? 0, 0);
		assert.equal(connection.closeHandlers.size, 0);
	});

	it("wait_for_agent aborts promptly on AbortSignal", async () => {
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

	it("list_agents requires agents skill invocation", async () => {
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
		const listTool = toolByName(tools, "list_agents");

		const result = await listTool.execute("1", {}, new AbortController().signal, () => {}, {});

		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);
		assert.equal(result.details, null);
	});
});
