import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { resolveDaemonPaths } from "../../../hub/index.ts";
import type { Frame } from "../../../hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "../../../hub/protocol/index.ts";
import { buildAgentTaskText } from "../executor.ts";
import { registerDaemonTools } from "../tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	setCurrentWorkspaceState,
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
			assert.equal(outbound.run_kind, "ad-hoc");
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

	it("dispatch_agent prefers protected root cwd and still passes --worktree-dir", async () => {
		trackSkillInvocation("agents");
		setCurrentWorkspaceState({
			launchCwd: "/wt",
			effectiveCwd: "/wt",
			scratchDir: "/tmp/pi/repo",
			unsafeEdit: false,
			repo: {
				root: "/repo-root",
				isRepo: true,
				name: "repo",
				remoteUrl: null,
			},
			protectedRoot: "/repo-root",
			activeWorktree: {
				path: "/wt",
				kind: "git-worktree",
				label: "wt",
				branch: null,
				created: false,
			},
		});

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
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.spec.cwd, "/repo-root");
			const worktreeDirIndex = outbound.spec.argv.indexOf("--worktree-dir");
			assert.notEqual(worktreeDirIndex, -1);
			assert.equal(outbound.spec.argv[worktreeDirIndex + 1], "/wt");

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			await executePromise;
		} finally {
			setCurrentWorkspaceState(null);
		}
	});

	it("dispatch_agent falls back to repo root cwd when protected root is unavailable", async () => {
		trackSkillInvocation("agents");
		setCurrentWorkspaceState({
			launchCwd: "/launch",
			effectiveCwd: "/launch",
			scratchDir: "/tmp/pi/repo",
			unsafeEdit: false,
			repo: {
				root: "/repo-root",
				isRepo: true,
				name: "repo",
				remoteUrl: null,
			},
			protectedRoot: null,
			activeWorktree: null,
		});

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
				{ model: "claude-sonnet", sessionManager: { getSessionId: () => "session-id" } },
			);

			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "dispatch" }>;
			assert.equal(outbound.spec.cwd, "/repo-root");

			connection.emit({
				type: "dispatch_ack",
				v: PROTOCOL_VERSION,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			await executePromise;
		} finally {
			setCurrentWorkspaceState(null);
		}
	});
});
