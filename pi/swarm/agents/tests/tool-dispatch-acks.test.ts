import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { registerDaemonTools } from "../daemon/tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("dispatch_agent guards and acks", () => {
	installDaemonToolTestHooks();

	it("dispatch_agent fails before daemon connection/send when agents skill has not been invoked", async () => {
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
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const result = await dispatchTool.execute("1", { task: "hello world" }, new AbortController().signal, () => {}, {
			model: "claude-sonnet",
			sessionManager: { getSessionId: () => "session-id" },
		});

		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);
		assert.equal(result.details, null);
	});

	it("dispatch_agent rejects invalid suffix before dispatching", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const result = await dispatchTool.execute(
			"1",
			{ task: "hello world", name: "../bad" },
			new AbortController().signal,
			() => {},
			{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
		);

		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /Invalid agent run-name suffix/i);
		assert.equal(connection.sent.length, 0);
	});

	it("dispatch_agent surfaces rejected ack reason as tool error", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const executePromise = dispatchTool.execute("1", { task: "hello world" }, new AbortController().signal, () => {}, {
			model: "claude-sonnet",
			sessionManager: { getSessionId: () => "session-id" },
		});
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: outbound.run_id,
			status: "rejected",
			reason: "depth_cap",
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.equal(result.details.agentHandle, outbound.agent_handle);
		assert.equal("agentId" in result.details, false);
		assert.match(result.content[0].text, /depth_cap/);

		const rendered = (dispatchTool as any)
			.renderResult(result, {}, { fg: (_token: string, text: string) => `styled:${text}` })
			.render(120)
			.join("\n");
		assert.match(rendered, /dispatch rejected: depth_cap/);
		assert.doesNotMatch(rendered, /⏳ dispatched/);
	});

	it("dispatch_agent retries generated handle collisions", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const executePromise = dispatchTool.execute(
			"1",
			{ agent: "scout", task: "hello world" },
			new AbortController().signal,
			() => {},
			{
				model: "claude-sonnet",
				sessionManager: { getSessionId: () => "session-id" },
			},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const first = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
		assert.match(first.agent_handle ?? "", /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		assert.equal(first.spec.env.BASECAMP_AGENT_HANDLE, first.agent_handle);
		assert.equal(first.agent_type, "scout");
		assert.equal(first.run_kind, "named-read-only");

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: first.run_id,
			status: "rejected",
			reason: "duplicate_agent_handle",
		});
		await new Promise((resolve) => setImmediate(resolve));

		const second = connection.sent[1] as Extract<Frame, { type: "dispatch" }>;
		assert.equal(second.agent_id, first.agent_id);
		assert.notEqual(second.run_id, first.run_id);
		assert.notEqual(second.agent_handle, first.agent_handle);
		assert.match(second.agent_handle ?? "", /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		assert.equal(second.spec.env.BASECAMP_AGENT_HANDLE, second.agent_handle);

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: second.run_id,
			status: "spawned",
			reason: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agentHandle, second.agent_handle);
		assert.match(result.content[0].text, new RegExp(String(second.agent_handle)));
	});

	it("dispatch_agent retasks an existing legacy type-prefixed handle with its internal agent id", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const executePromise = dispatchTool.execute(
			"1",
			{ agent_handle: "scout-amber-fox-a1b2c3", task: "follow up" },
			new AbortController().signal,
			() => {},
			{
				model: "claude-sonnet",
				sessionManager: { getSessionId: () => "session-id" },
			},
		);
		await new Promise((resolve) => setImmediate(resolve));

		const listRequest = connection.sent[0] as Extract<Frame, { type: "list_agents" }>;
		assert.equal(listRequest.type, "list_agents");
		connection.emit({
			type: "list_agents_result",
			v: PROTOCOL_VERSION,
			request_id: listRequest.request_id,
			agents: [
				{
					agent_id: "00000000-0000-4000-8000-000000000001",
					agent_handle: "scout-amber-fox-a1b2c3",
					agent_type: "scout",
					run_kind: "named-read-only",
					parent_id: "session-id",
					role: "agent",
					session_name: "scout-amber-fox-a1b2c3",
					depth: 1,
					status: "completed",
					awaitable: true,
				},
			],
		});
		await new Promise((resolve) => setImmediate(resolve));

		const dispatch = connection.sent[1] as Extract<Frame, { type: "dispatch" }>;
		assert.equal(dispatch.agent_id, "00000000-0000-4000-8000-000000000001");
		assert.equal(dispatch.agent_handle, "scout-amber-fox-a1b2c3");
		assert.equal(dispatch.agent_type, "scout");
		assert.equal(dispatch.run_kind, "named-read-only");

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: dispatch.run_id,
			status: "spawned",
			reason: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agentHandle, "scout-amber-fox-a1b2c3");
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000001/);
	});

	it("dispatch_agent rejects changing an existing legacy handle's agent type", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const resultPromise = dispatchTool.execute(
			"1",
			{ agent: "worker", agent_handle: "scout-amber-fox-a1b2c3", task: "follow up" },
			new AbortController().signal,
			() => {},
			{
				model: "claude-sonnet",
				sessionManager: { getSessionId: () => "session-id" },
			},
		);
		await new Promise((resolve) => setImmediate(resolve));

		const listRequest = connection.sent[0] as Extract<Frame, { type: "list_agents" }>;
		connection.emit({
			type: "list_agents_result",
			v: PROTOCOL_VERSION,
			request_id: listRequest.request_id,
			agents: [
				{
					agent_id: "00000000-0000-4000-8000-000000000001",
					agent_handle: "scout-amber-fox-a1b2c3",
					agent_type: "scout",
					run_kind: "named-read-only",
					parent_id: "session-id",
					role: "agent",
					session_name: "scout-amber-fox-a1b2c3",
					depth: 1,
					status: "completed",
					awaitable: true,
				},
			],
		});

		const result = await resultPromise;
		assert.equal(result.isError, true);
		assert.equal(connection.sent.length, 1);
		assert.match(result.content[0].text, /is scout; use a new handle for worker/);
	});
});
