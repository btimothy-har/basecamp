import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { resolveDaemonPaths } from "#core/hub/index.ts";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { buildAgentTaskText } from "#core/swarm/agents/executor.ts";
import { registerDaemonTools } from "#core/swarm/agents/tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("dispatch_agent", () => {
	installDaemonToolTestHooks();

	it("registerDaemonTools includes dispatch, ask, peer messaging, cancel, list, and wait tools", () => {
		const { pi, tools } = createMockPi();

		registerDaemonTools(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			[
				"dispatch_agent",
				"ask_agent",
				"message_agent",
				"message_status",
				"cancel_agent",
				"list_agents",
				"wait_for_agent",
			],
		);
	});

	it("dispatch_agent builds spec env/task split and returns handle on spawned ack", async () => {
		trackSkillInvocation("agents");
		const priorCustom = process.env.TEST_DAEMON_TOOLS;
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorProject = process.env.BASECAMP_PROJECT;
		process.env.TEST_DAEMON_TOOLS = "1";
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.BASECAMP_PROJECT = "proj";

		try {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");

			const executePromise = dispatchTool.execute(
				"1",
				{ task: "hello world" },
				new AbortController().signal,
				() => {},
				{ model: { provider: "anthropic", id: "claude-sonnet" }, sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.type, "dispatch");
			assert.equal(outbound.spec.task, buildAgentTaskText("hello world"));
			assert.notEqual(outbound.spec.argv.at(-1), buildAgentTaskText("hello world"));
			assert.equal(outbound.spec.env.TEST_DAEMON_TOOLS, "1");
			assert.equal(outbound.spec.env.BASECAMP_PROJECT, "proj");
			assert.equal(outbound.spec.env.BASECAMP_PARENT_SESSION, process.env.BASECAMP_SESSION_NAME ?? "session-name");
			assert.equal(outbound.spec.env.BASECAMP_AGENT_TITLE, "(Agent) hello world");
			assert.equal(outbound.spec.env.BASECAMP_AGENT_HANDLE, outbound.agent_handle);
			assert.match(outbound.agent_handle ?? "", /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
			assert.notEqual(outbound.agent_handle, outbound.agent_id);
			assert.equal(outbound.agent_type, "ad-hoc");
			assert.equal(outbound.model, "anthropic/claude-sonnet");

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});

			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.equal(result.details.agentHandle, outbound.agent_handle);
			assert.equal("agentId" in result.details, false);
			assert.equal("runId" in result.details, false);
			assert.match(result.content[0].text, new RegExp(String(outbound.agent_handle)));
			assert.doesNotMatch(result.content[0].text, new RegExp(String(outbound.agent_id)));
			assert.doesNotMatch(result.content[0].text, new RegExp(String(outbound.run_id)));
		} finally {
			if (priorCustom === undefined) delete process.env.TEST_DAEMON_TOOLS;
			else process.env.TEST_DAEMON_TOOLS = priorCustom;
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorProject === undefined) delete process.env.BASECAMP_PROJECT;
			else process.env.BASECAMP_PROJECT = priorProject;
		}
	});

	it("dispatch_agent propagates the sandbox trio only under the full launch state", async () => {
		trackSkillInvocation("agents");
		const prior = {
			reviewer: process.env.BASECAMP_BASH_REVIEWER,
			sandbox: process.env.BASECAMP_EXTERNAL_SANDBOX,
		};
		process.env.BASECAMP_BASH_REVIEWER = "off";
		process.env.BASECAMP_EXTERNAL_SANDBOX = "1";

		const dispatchSpec = async (sandboxedFlag: boolean) => {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			pi.flags["unsafe-edit-sandboxed"] = sandboxedFlag;
			registerDaemonTools(pi, async () => connection, daemonToolDeps);
			const dispatchTool = toolByName(tools, "dispatch_agent");
			const executePromise = dispatchTool.execute("1", { task: "hello" }, new AbortController().signal, () => {}, {
				model: "claude-sonnet",
				sessionManager: { getSessionId: () => "session-id" },
			});
			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			await executePromise;
			return outbound.spec;
		};

		try {
			// Env pair present but no parent launch flag: the pair must not reach the child
			// through the {...processEnvForSpawn(), ...plan.environment} merge, and the child
			// argv must not carry the flag.
			const bare = await dispatchSpec(false);
			assert.equal(bare.env.BASECAMP_BASH_REVIEWER, undefined);
			assert.equal(bare.env.BASECAMP_EXTERNAL_SANDBOX, undefined);
			assert.equal(bare.argv.includes("--unsafe-edit-sandboxed"), false);

			// Full launch state: pair + flag propagate together.
			const sandboxed = await dispatchSpec(true);
			assert.equal(sandboxed.env.BASECAMP_BASH_REVIEWER, "off");
			assert.equal(sandboxed.env.BASECAMP_EXTERNAL_SANDBOX, "1");
			assert.equal(sandboxed.argv.includes("--unsafe-edit-sandboxed"), true);
			assert.equal(sandboxed.argv.includes("--unsafe-edit"), false);
		} finally {
			if (prior.reviewer === undefined) delete process.env.BASECAMP_BASH_REVIEWER;
			else process.env.BASECAMP_BASH_REVIEWER = prior.reviewer;
			if (prior.sandbox === undefined) delete process.env.BASECAMP_EXTERNAL_SANDBOX;
			else process.env.BASECAMP_EXTERNAL_SANDBOX = prior.sandbox;
		}
	});

	it("dispatch_agent uses buildPiArgs final task arg for long task text", async () => {
		trackSkillInvocation("agents");
		const longTask = "x".repeat(9_000);
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const dispatchTool = toolByName(tools, "dispatch_agent");

		const executePromise = dispatchTool.execute("1", { task: longTask }, new AbortController().signal, () => {}, {
			model: "claude-sonnet",
			sessionManager: { getSessionId: () => "session-id" },
		});

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
		assert.equal(outbound.type, "dispatch");
		assert.match(outbound.spec.task, /^@/);
		assert.equal(outbound.spec.task.startsWith("Task: "), false);
		assert.notEqual(outbound.spec.argv.at(-1), outbound.spec.task);
		assert.equal(outbound.spec.task.endsWith("task.md"), true);
		const taskFile = outbound.spec.task.startsWith("@") ? outbound.spec.task.slice(1) : outbound.spec.task;
		assert.match(taskFile, /task\.md$/);
		assert.equal(fs.readFileSync(taskFile, "utf8"), buildAgentTaskText(longTask));

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: outbound.run_id,
			status: "spawned",
			reason: null,
		});

		await executePromise;
	});

	it("dispatch_agent uses matching agent_id, --session-id, and durable session directory segment", async () => {
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
		const sessionDirFlagIndex = outbound.spec.argv.indexOf("--session-dir");
		assert.notEqual(sessionDirFlagIndex, -1);
		const sessionDir = outbound.spec.argv[sessionDirFlagIndex + 1];
		if (typeof sessionDir !== "string") throw new Error("Missing --session-dir value");
		assert.equal(path.basename(sessionDir), "session");
		assert.equal(sessionDir.startsWith(path.join(resolveDaemonPaths().runtimeDir, "agents")), true);
		assert.equal(sessionDir.includes("basecamp-agents"), false);

		const agentSegment = path.basename(path.dirname(sessionDir));
		assert.match(agentSegment, /^[0-9a-f-]{36}$/);

		const sessionIdFlagIndex = outbound.spec.argv.indexOf("--session-id");
		assert.notEqual(sessionIdFlagIndex, -1);
		const sessionId = outbound.spec.argv[sessionIdFlagIndex + 1];
		assert.equal(sessionId, agentSegment);
		assert.equal(outbound.agent_id, agentSegment);
		assert.match(outbound.agent_handle ?? "", /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		assert.notEqual(outbound.agent_handle, agentSegment);

		connection.emit({
			type: "dispatch_ack",
			v: PROTOCOL_VERSION,
			run_id: outbound.run_id,
			status: "spawned",
			reason: null,
		});
		await executePromise;
	});
});
