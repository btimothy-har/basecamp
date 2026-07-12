import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { registerAskAgentTool, registerDaemonTools } from "../daemon/tools.ts";
import { buildAgentTaskText } from "../executor.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("ask_agent", () => {
	installDaemonToolTestHooks();

	it("registerAskAgentTool registers only ask_agent", () => {
		const { pi, tools } = createMockPi();

		registerAskAgentTool(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			["ask_agent"],
		);
	});

	it("ask_agent dispatches forked ask agent, waits, and returns answer text", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const askTool = toolByName(tools, "ask_agent");

		const executePromise = askTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", question: "What did you find?", timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
		);

		await new Promise((resolve) => setImmediate(resolve));
		const dispatch = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
		assert.equal(dispatch.type, "dispatch");
		assert.equal(dispatch.agent_type, "ask");
		assert.equal(dispatch.spec.fork_from, "amber-fox-a1b2c3");
		assert.equal(dispatch.spec.task, buildAgentTaskText("What did you find?"));
		assert.match(dispatch.agent_handle ?? "", /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		assert.equal(dispatch.spec.env.BASECAMP_AGENT_HANDLE, dispatch.agent_handle);
		const agentTitle = dispatch.spec.env.BASECAMP_AGENT_TITLE ?? "";
		assert.ok(agentTitle.startsWith("(ask → amber-fox-a1b2c3) "));

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: dispatch.run_id,
			status: "spawned",
			reason: null,
		});
		await new Promise((resolve) => setImmediate(resolve));

		const wait = connection.sent[1] as Extract<Frame, { type: "wait" }>;
		assert.equal(wait.type, "wait");
		assert.deepEqual(wait.agent_handles, [dispatch.agent_handle]);
		assert.equal(wait.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: PROTOCOL_VERSION,
			results: [
				{ agent_handle: dispatch.agent_handle, status: "completed", result: "Here is the answer.", error: null },
			],
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.content[0].text, "Here is the answer.");
		assert.equal(result.details.agentHandle, dispatch.agent_handle);
		assert.equal(result.details.status, "completed");
		assert.equal(result.details.answer, "Here is the answer.");
	});

	it("ask_agent returns non-leaky error and does not wait when fork target is unknown", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const askTool = toolByName(tools, "ask_agent");

		const executePromise = askTool.execute(
			"1",
			{ agent_handle: "missing-agent", question: "Can you answer this?", timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
		);

		await new Promise((resolve) => setImmediate(resolve));
		const dispatch = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
		assert.equal(dispatch.type, "dispatch");
		assert.equal(dispatch.agent_type, "ask");
		assert.equal(dispatch.spec.fork_from, "missing-agent");

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: dispatch.run_id,
			status: "rejected",
			reason: "fork_target_unknown",
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.equal(result.content[0].text, "No available agent for that handle.");
		assert.doesNotMatch(result.content[0].text, /missing-agent/);
		assert.equal(connection.sent.length, 1);
	});

	it("ask_agent rejects a whitespace-only agent_handle without dispatching", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const askTool = toolByName(tools, "ask_agent");

		const result = await askTool.execute(
			"1",
			{ agent_handle: "   ", question: "What did you find?", timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
		);

		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /non-empty agent_handle/);
		assert.equal(connection.sent.length, 0);
	});
});
