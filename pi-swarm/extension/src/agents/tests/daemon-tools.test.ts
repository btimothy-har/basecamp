import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { WorkspaceState } from "../../dependencies.ts";
import { createDaemonClient, type DaemonConnection } from "../daemon/client.ts";
import type { Frame, ListAgentItem } from "../daemon/frames.ts";
import { deriveDaemonIdentity } from "../daemon/index.ts";
import { resolveDaemonPaths } from "../daemon/paths.ts";
import { registerDaemonTools } from "../daemon/tools.ts";
import { buildAgentTitleBase, processEnvForSpawn } from "../launch.ts";

interface RegisteredTool {
	name: string;
	execute: (id: string, params: any, signal: AbortSignal, onUpdate: () => void, ctx: any) => Promise<any>;
}

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

	close(): void {
		this.emitClose(1000, "client closed");
	}

	emit(frame: Frame): void {
		const set = this.handlers.get(frame.type);
		if (!set) return;
		for (const handler of set) handler(frame as any);
	}

	emitClose(code: number, reason: string): void {
		for (const handler of this.closeHandlers) handler(code, reason);
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

const invokedSkills = new Set<string>();
let currentWorkspaceState: WorkspaceState | null = null;

function trackSkillInvocation(name: string): void {
	invokedSkills.add(name);
}

function resetInvokedSkills(): void {
	invokedSkills.clear();
}

const daemonToolDeps = {
	hasInvokedSkill: (name: string) => invokedSkills.has(name),
	getWorkspaceState: () => currentWorkspaceState,
	basecampExtensionRoot: process.cwd(),
	resolveModelAlias: (model: string) => model,
	readSkillContent: (_path: string) => null,
	buildSkillBlock: (_name: string, content: string) => content,
};

describe("daemon async tools", () => {
	let priorHome: string | undefined;
	let tmpHome: string;

	beforeEach(() => {
		priorHome = process.env.HOME;
		tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), "bc-test-home-"));
		process.env.HOME = tmpHome;
		resetInvokedSkills();
	});

	afterEach(() => {
		if (priorHome === undefined) delete process.env.HOME;
		else process.env.HOME = priorHome;
		fs.rmSync(tmpHome, { recursive: true, force: true });
		currentWorkspaceState = null;
		resetInvokedSkills();
	});

	describe("buildAgentTitleBase", () => {
		it("formats named/ad-hoc titles, compacts whitespace, and truncates long tasks", () => {
			assert.equal(buildAgentTitleBase("scout", "Investigate the auth flow"), "(scout) Investigate the auth flow");
			assert.equal(buildAgentTitleBase(undefined, "hello world"), "(Agent) hello world");
			assert.equal(buildAgentTitleBase("worker", "do   a\n  thing"), "(worker) do a thing");

			const longTask = "x".repeat(80);
			const truncated = buildAgentTitleBase("worker", longTask);
			assert.equal(truncated.endsWith("…"), true);
			assert.ok(truncated.length <= "(worker) ".length + 56);
		});
	});

	describe("processEnvForSpawn", () => {
		it("strips daemon report identity vars while preserving ordinary env", () => {
			const prior = {
				runId: process.env.BASECAMP_RUN_ID,
				reportToken: process.env.BASECAMP_REPORT_TOKEN,
				agentId: process.env.BASECAMP_AGENT_ID,
				daemonUds: process.env.BASECAMP_DAEMON_UDS,
				project: process.env.BASECAMP_PROJECT,
				apiKey: process.env.DAEMON_TEST_API_KEY,
			};
			process.env.BASECAMP_RUN_ID = "run-parent";
			process.env.BASECAMP_REPORT_TOKEN = "report-parent";
			process.env.BASECAMP_AGENT_ID = "agent-parent";
			process.env.BASECAMP_DAEMON_UDS = "/tmp/daemon-parent.sock";
			process.env.BASECAMP_PROJECT = "proj-parent";
			process.env.DAEMON_TEST_API_KEY = "parent-api-key";

			try {
				const env = processEnvForSpawn();
				assert.equal(env.BASECAMP_RUN_ID, undefined);
				assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
				assert.equal(env.BASECAMP_AGENT_ID, undefined);
				assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
				assert.equal(env.BASECAMP_PROJECT, "proj-parent");
				assert.equal(env.DAEMON_TEST_API_KEY, "parent-api-key");
			} finally {
				if (prior.runId === undefined) delete process.env.BASECAMP_RUN_ID;
				else process.env.BASECAMP_RUN_ID = prior.runId;
				if (prior.reportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
				else process.env.BASECAMP_REPORT_TOKEN = prior.reportToken;
				if (prior.agentId === undefined) delete process.env.BASECAMP_AGENT_ID;
				else process.env.BASECAMP_AGENT_ID = prior.agentId;
				if (prior.daemonUds === undefined) delete process.env.BASECAMP_DAEMON_UDS;
				else process.env.BASECAMP_DAEMON_UDS = prior.daemonUds;
				if (prior.project === undefined) delete process.env.BASECAMP_PROJECT;
				else process.env.BASECAMP_PROJECT = prior.project;
				if (prior.apiKey === undefined) delete process.env.DAEMON_TEST_API_KEY;
				else process.env.DAEMON_TEST_API_KEY = prior.apiKey;
			}
		});
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
			assert.equal(outbound.spec.env.BASECAMP_AGENT_TITLE, "(Agent) hello world");

			connection.emit({
				type: "dispatch_ack",
				v: 4,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});

			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.equal(result.details.agentId, outbound.agent_id);
			assert.equal("runId" in result.details, false);
			assert.match(result.content[0].text, new RegExp(String(outbound.agent_id)));
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

		connection.emit({
			type: "dispatch_ack",
			v: 4,
			run_id: outbound.run_id,
			status: "spawned",
			reason: null,
		});
		await executePromise;
	});

	it("dispatch_agent prefers protected root cwd and still passes --worktree-dir", async () => {
		trackSkillInvocation("agents");
		currentWorkspaceState = {
			launchCwd: "/wt",
			repo: {
				root: "/repo-root",
			},
			protectedRoot: "/repo-root",
			activeWorktree: {
				path: "/wt",
			},
		};

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
				v: 4,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			await executePromise;
		} finally {
			currentWorkspaceState = null;
		}
	});

	it("dispatch_agent falls back to repo root cwd when protected root is unavailable", async () => {
		trackSkillInvocation("agents");
		currentWorkspaceState = {
			launchCwd: "/launch",
			repo: {
				root: "/repo-root",
			},
			protectedRoot: null,
			activeWorktree: null,
		};

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
				v: 4,
				run_id: outbound.run_id,
				status: "spawned",
				reason: null,
			});
			await executePromise;
		} finally {
			currentWorkspaceState = null;
		}
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
			v: 4,
			run_id: outbound.run_id,
			status: "rejected",
			reason: "depth_cap",
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.match(result.content[0].text, /depth_cap/);
	});

	it("wait_for_agent sends wait and returns per-handle results", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerDaemonTools(pi, async () => connection, daemonToolDeps);
		const waitTool = toolByName(tools, "wait_for_agent");

		const executePromise = waitTool.execute(
			"1",
			{ handles: ["agent-1", "agent-2"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_ids, ["agent-1", "agent-2"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: 4,
			results: [
				{ agent_id: "agent-1", status: "completed", result: "duplicate", error: null },
				{ agent_id: "agent-1", status: "completed", result: "duplicate", error: null },
			],
		});
		connection.emit({
			type: "wait_result",
			v: 4,
			results: [
				{ agent_id: "agent-1", status: "completed", result: "done", error: null },
				{ agent_id: "agent-2", status: "failed", result: "compensation skipped", error: "boom" },
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
			{ handles: ["agent-1", "agent-2", "agent-3"], timeout_s: 30 },
			new AbortController().signal,
			() => {},
			{},
		);

		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "wait" }>;
		assert.equal(outbound.type, "wait");
		assert.deepEqual(outbound.agent_ids, ["agent-1", "agent-2", "agent-3"]);
		assert.equal(outbound.timeout_s, 30);

		connection.emit({
			type: "wait_result",
			v: 4,
			results: [
				{ agent_id: "agent-1", status: "running", result: null, error: null },
				{ agent_id: "agent-2", status: "unknown", result: null, error: null },
				{ agent_id: "agent-3", status: "completed", result: "ok", error: null },
			],
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.items[0].status, "running");
		assert.equal(result.details.items[1].status, "unknown");
		assert.equal(result.details.items[2].status, "completed");
		assert.match(result.content[0].text, /still running \(timed out\)/);
		assert.match(result.content[0].text, /\? agent-2 unknown agent/);
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
			{ handles: ["agent-1"], timeout_s: 30 },
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
			v: 4 as 4,
			request_id: outbound.request_id,
			agents: [
				{
					agent_id: "agent-1",
					parent_id: "session-1",
					role: "agent",
					session_name: "agent-one",
					depth: 1,
					status: "running",
					awaitable: true,
				},
				{
					agent_id: "agent-2",
					parent_id: "agent-1",
					role: "agent",
					session_name: "agent-two",
					depth: 2,
					status: "completed",
					awaitable: false,
				},
			] as ListAgentItem[],
		} as Extract<Frame, { type: "list_agents_result" }>;
		connection.emit(response);

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agents.length, 2);
		assert.equal(result.details.agents[0].agent_id, "agent-1");
		assert.equal(result.details.agents[1].status, "completed");
		assert.match(result.content[0].text, /agent-1/);
		assert.match(result.content[0].text, /agent-one/);
		assert.match(result.content[0].text, /agent-two/);
		assert.match(result.content[0].text, /running/);
		assert.match(result.content[0].text, /completed/);
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
			{ handles: "agent-1", timeout_s: 30 },
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

	it("deriveDaemonIdentity prefers BASECAMP_AGENT_TITLE with short session-id suffix", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-xyz";
		process.env.BASECAMP_AGENT_TITLE = "(scout) do thing";

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "0199-aaaa-bbbb-cccc-ddddeeee9f3c" },
			} as any);
			assert.equal(identity.session_name, "(scout) do thing [9f3c]");
			assert.equal(identity.role, "agent");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
		}
	});

	it("deriveDaemonIdentity falls back to BASECAMP_SESSION_NAME or node id when BASECAMP_AGENT_TITLE is unset", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;
		const priorSessionName = process.env.BASECAMP_SESSION_NAME;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-fallback";
		delete process.env.BASECAMP_AGENT_TITLE;

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "session-id" },
			} as any);
			assert.equal(identity.session_name, process.env.BASECAMP_SESSION_NAME ?? "agent-fallback");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
			if (priorSessionName === undefined) delete process.env.BASECAMP_SESSION_NAME;
			else process.env.BASECAMP_SESSION_NAME = priorSessionName;
		}
	});
});
