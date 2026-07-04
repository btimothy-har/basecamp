import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { WorkspaceState } from "../../dependencies.ts";
import { createDaemonClient, type DaemonConnection } from "../daemon/client.ts";
import type { Frame, ListAgentItem } from "../daemon/frames.ts";
import { PROTOCOL_VERSION } from "../daemon/frames.ts";
import { deriveDaemonIdentity } from "../daemon/index.ts";
import { resolveDaemonPaths } from "../daemon/paths.ts";
import { registerAskAgentTool, registerDaemonTools, registerPeerMessageTools } from "../daemon/tools.ts";
import { buildAgentTaskText } from "../executor.ts";
import { buildAgentEnv, buildAgentTitleBase, processEnvForSpawn } from "../launch.ts";

interface RegisteredTool {
	name: string;
	description?: string;
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
	const handlers = new Map<string, ((event: any, ctx: any) => void)[]>();
	const pi = {
		registerTool(tool: RegisteredTool) {
			tools.push(tool);
		},
		on(event: string, handler: (event: any, ctx: any) => void) {
			handlers.set(event, [...(handlers.get(event) ?? []), handler]);
		},
		getSessionName() {
			return "session-name";
		},
		getAllTools() {
			return [];
		},
		sendUserMessage() {},
		setSessionName() {},
	};
	return { pi: pi as any, tools, handlers };
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

	describe("buildAgentEnv", () => {
		it("sets parent session as sibling group for spawned agents", () => {
			const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
			const priorProject = process.env.BASECAMP_PROJECT;
			const priorParent = process.env.BASECAMP_PARENT_SESSION;
			const priorSiblingGroup = process.env.BASECAMP_SIBLING_GROUP;
			const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;
			process.env.BASECAMP_AGENT_DEPTH = "1";
			process.env.BASECAMP_PROJECT = "parent-project";
			process.env.BASECAMP_PARENT_SESSION = "old-parent";
			process.env.BASECAMP_SIBLING_GROUP = "old-sibling-group";
			process.env.BASECAMP_AGENT_HANDLE = "parent-handle";

			try {
				const env = buildAgentEnv({
					name: "agent-name",
					parentSession: "dispatcher-node",
					project: "child-project",
				});

				assert.equal(env.BASECAMP_PROJECT, "child-project");
				assert.equal(env.BASECAMP_PARENT_SESSION, "dispatcher-node");
				assert.equal(env.BASECAMP_SIBLING_GROUP, "dispatcher-node");
				assert.equal(env.BASECAMP_AGENT_DEPTH, "2");
				assert.equal(env.BASECAMP_AGENT_HANDLE, undefined);
			} finally {
				if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
				else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
				if (priorProject === undefined) delete process.env.BASECAMP_PROJECT;
				else process.env.BASECAMP_PROJECT = priorProject;
				if (priorParent === undefined) delete process.env.BASECAMP_PARENT_SESSION;
				else process.env.BASECAMP_PARENT_SESSION = priorParent;
				if (priorSiblingGroup === undefined) delete process.env.BASECAMP_SIBLING_GROUP;
				else process.env.BASECAMP_SIBLING_GROUP = priorSiblingGroup;
				if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
				else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
			}
		});
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
				agentHandle: process.env.BASECAMP_AGENT_HANDLE,
				project: process.env.BASECAMP_PROJECT,
				apiKey: process.env.DAEMON_TEST_API_KEY,
			};
			process.env.BASECAMP_RUN_ID = "run-parent";
			process.env.BASECAMP_REPORT_TOKEN = "report-parent";
			process.env.BASECAMP_AGENT_ID = "agent-parent";
			process.env.BASECAMP_DAEMON_UDS = "/tmp/daemon-parent.sock";
			process.env.BASECAMP_AGENT_HANDLE = "parent-handle";
			process.env.BASECAMP_PROJECT = "proj-parent";
			process.env.DAEMON_TEST_API_KEY = "parent-api-key";

			try {
				const env = processEnvForSpawn();
				assert.equal(env.BASECAMP_RUN_ID, undefined);
				assert.equal(env.BASECAMP_REPORT_TOKEN, undefined);
				assert.equal(env.BASECAMP_AGENT_ID, undefined);
				assert.equal(env.BASECAMP_DAEMON_UDS, undefined);
				assert.equal(env.BASECAMP_AGENT_HANDLE, undefined);
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
				if (prior.agentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
				else process.env.BASECAMP_AGENT_HANDLE = prior.agentHandle;
				if (prior.project === undefined) delete process.env.BASECAMP_PROJECT;
				else process.env.BASECAMP_PROJECT = prior.project;
				if (prior.apiKey === undefined) delete process.env.DAEMON_TEST_API_KEY;
				else process.env.DAEMON_TEST_API_KEY = prior.apiKey;
			}
		});
	});

	it("registerAskAgentTool registers only ask_agent", () => {
		const { pi, tools } = createMockPi();

		registerAskAgentTool(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			["ask_agent"],
		);
	});

	it("registerPeerMessageTools registers message_agent and message_status", () => {
		const { pi, tools } = createMockPi();

		registerPeerMessageTools(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			["message_agent", "message_status"],
		);
	});

	it("registerDaemonTools includes dispatch, ask, peer messaging, list, and wait tools", () => {
		const { pi, tools } = createMockPi();

		registerDaemonTools(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			["dispatch_agent", "ask_agent", "message_agent", "message_status", "list_agents", "wait_for_agent"],
		);
	});

	it("message_agent and ask_agent describe known-public-handle contact across sessions", () => {
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => new MockConnection(), daemonToolDeps);
		registerAskAgentTool(pi, async () => new MockConnection(), daemonToolDeps);

		const messageDescription = toolByName(tools, "message_agent").description ?? "";
		const askDescription = toolByName(tools, "ask_agent").description ?? "";

		assert.match(messageDescription, /known public handle/i);
		assert.match(messageDescription, /without a live parent\/child\/sibling relationship/i);
		assert.match(askDescription, /known public handle/i);
		assert.match(askDescription, /without a live parent\/child\/sibling relationship/i);
	});

	it("message_agent sends peer_message and returns accepted message_id without waiting for delivery or answers", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");

		const executePromise = messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "Please consider this update.", interrupt: true },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		assert.equal(outbound.type, "peer_message");
		assert.equal(outbound.target_handle, "amber-fox-a1b2c3");
		assert.equal(outbound.message, "Please consider this update.");
		assert.equal(outbound.interrupt, true);
		assert.equal(typeof outbound.request_id, "string");

		let resolved = false;
		executePromise.then(() => {
			resolved = true;
		});
		connection.emit({
			type: "peer_message_delivery",
			v: PROTOCOL_VERSION,
			message_id: "message-1",
			from_handle: "sender",
			from_relation: "peer",
			message: "recipient delivery is not a response",
			interrupt: false,
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(resolved, false);

		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-accepted",
			status: "accepted",
			error: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agentHandle, "amber-fox-a1b2c3");
		assert.equal(result.details.messageId, "message-accepted");
		assert.equal(result.details.status, "accepted");
		assert.equal("agent_id" in result.details, false);
		assert.equal("run_id" in result.details, false);
		assert.match(result.content[0].text, /message_id message-accepted/);
		assert.doesNotMatch(result.content[0].text, /agent_id|run_id/);
	});

	it("message_agent handles unknown targets without leaking private ids", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");

		const executePromise = messageTool.execute(
			"1",
			{ agent_handle: "missing-agent", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: null,
			status: "unknown",
			error: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.equal(result.details.messageId, null);
		assert.equal(result.details.status, "unknown");
		assert.match(result.content[0].text, /No agent "missing-agent" is available to message/);
		assert.doesNotMatch(JSON.stringify(result), /agent_id|run_id/);
	});

	it("message_agent validates empty input and requires the agents skill", async () => {
		let connected = false;
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(
			pi,
			async () => {
				connected = true;
				return new MockConnection();
			},
			daemonToolDeps,
		);
		const messageTool = toolByName(tools, "message_agent");

		const noSkill = await messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(noSkill.isError, true);
		assert.match(noSkill.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);

		trackSkillInvocation("agents");
		const emptyHandle = await messageTool.execute(
			"2",
			{ agent_handle: "   ", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(emptyHandle.isError, true);
		assert.match(emptyHandle.content[0].text, /non-empty agent_handle/);
		assert.equal(connected, false);

		const emptyMessage = await messageTool.execute(
			"3",
			{ agent_handle: "amber-fox-a1b2c3", message: "   " },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(emptyMessage.isError, true);
		assert.match(emptyMessage.content[0].text, /non-empty message/);
		assert.equal(connected, false);
	});

	it("message_status sends status requests and returns lifecycle fields for all statuses", async () => {
		trackSkillInvocation("agents");
		const statuses = ["accepted", "sent", "queued", "failed", "unavailable", "unknown"] as const;
		for (const status of statuses) {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
			const statusTool = toolByName(tools, "message_status");

			const executePromise = statusTool.execute(
				"1",
				{ message_id: `message-${status}` },
				new AbortController().signal,
				() => {},
				{},
			);
			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
			assert.equal(outbound.type, "message_status");
			assert.equal(typeof outbound.request_id, "string");
			assert.equal(outbound.message_id, `message-${status}`);
			assert.equal(outbound.wait_until_delivery, false);
			assert.equal(outbound.timeout_s, undefined);

			connection.emit({
				type: "message_status_result",
				v: PROTOCOL_VERSION,
				request_id: outbound.request_id,
				message_id: `message-${status}`,
				status,
				error: status === "failed" ? "delivery failed" : null,
				created_at: "2026-01-01T00:00:00Z",
				sent_at: status === "sent" || status === "queued" ? "2026-01-01T00:00:01Z" : null,
				queued_at: status === "queued" ? "2026-01-01T00:00:02Z" : null,
				failed_at: status === "failed" ? "2026-01-01T00:00:03Z" : null,
			});

			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.equal(result.details.messageId, `message-${status}`);
			assert.equal(result.details.status, status);
			assert.equal(result.details.createdAt, "2026-01-01T00:00:00Z");
			assert.match(result.content[0].text, new RegExp(`status ${status}`));
			assert.doesNotMatch(JSON.stringify(result), /answer|agent_id|run_id/);
		}
	});

	it("message_status supports wait flag, timeout, abort, validation, and skill enforcement", async () => {
		let connected = false;
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(
			pi,
			async () => {
				connected = true;
				return connection;
			},
			daemonToolDeps,
		);
		const statusTool = toolByName(tools, "message_status");

		const noSkill = await statusTool.execute(
			"1",
			{ message_id: "message-1" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(noSkill.isError, true);
		assert.match(noSkill.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);

		trackSkillInvocation("agents");
		const emptyId = await statusTool.execute("2", { message_id: "   " }, new AbortController().signal, () => {}, {});
		assert.equal(emptyId.isError, true);
		assert.match(emptyId.content[0].text, /non-empty message_id/);
		assert.equal(connected, false);

		const executePromise = statusTool.execute(
			"3",
			{ message_id: "message-wait", wait_until_delivery: true, timeout_s: 12.8 },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.wait_until_delivery, true);
		assert.equal(outbound.timeout_s, 12);
		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-wait",
			status: "unavailable",
			error: "target offline",
			created_at: "2026-01-01T00:00:00Z",
			sent_at: null,
			queued_at: null,
			failed_at: "2026-01-01T00:00:04Z",
		});
		const waitResult = await executePromise;
		assert.equal(waitResult.details.status, "unavailable");
		assert.equal(waitResult.details.error, "target offline");

		const controller = new AbortController();
		const abortPromise = statusTool.execute(
			"4",
			{ message_id: "message-abort", wait_until_delivery: true, timeout_s: 30 },
			controller.signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		controller.abort();
		const abortResult = await abortPromise;
		assert.equal(abortResult.details.aborted, true);
		assert.match(abortResult.content[0].text, /aborted/);
	});

	it("peer message renderers stay compact and do not expose private ids", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");
		const statusTool = toolByName(tools, "message_status");
		const theme = { fg: (_token: string, text: string) => `styled:${text}` };

		const messagePromise = messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const peer = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: peer.request_id,
			message_id: "message-render",
			status: "accepted",
			error: null,
		});
		const messageResult = await messagePromise;
		const renderedMessage = (messageTool as any).renderResult(messageResult, {}, theme).render(120).join("\n");
		assert.match(renderedMessage, /message_id message-render/);
		assert.doesNotMatch(renderedMessage, /agent_id|run_id|00000000-0000-4000-8000/);

		const statusPromise = statusTool.execute(
			"2",
			{ message_id: "message-render" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const status = connection.sent[1] as Extract<Frame, { type: "message_status" }>;
		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: status.request_id,
			message_id: "message-render",
			status: "queued",
			error: null,
			created_at: "2026-01-01T00:00:00Z",
			sent_at: "2026-01-01T00:00:01Z",
			queued_at: "2026-01-01T00:00:02Z",
			failed_at: null,
		});
		const statusResult = await statusPromise;
		const renderedStatus = (statusTool as any).renderResult(statusResult, {}, theme).render(120).join("\n");
		assert.match(renderedStatus, /message_id message-render/);
		assert.match(renderedStatus, /status queued/);
		assert.doesNotMatch(renderedStatus, /answer|agent_id|run_id/);
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
		currentWorkspaceState = {
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
				v: PROTOCOL_VERSION,
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
				v: PROTOCOL_VERSION,
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
		assert.equal(result.content[0].text, 'No agent "missing-agent" is available to ask.');
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
		assert.match(result.content[0].text, /\? scout-missing unknown agent/);
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
					parent_id: "session-1",
					role: "agent",
					session_name: "agent-one",
					depth: 1,
					status: "running",
					awaitable: true,
				},
				{
					agent_id: "00000000-0000-4000-8000-000000000002",
					agent_handle: "mossy-lynx-d4e5f6",
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
					parent_id: "session-1",
					role: "agent",
					session_name: "00000000-0000-4000-8000-000000000004",
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
		assert.equal("agent_id" in result.details.agents[0], false);
		assert.equal(result.details.agents[1].status, "completed");
		assert.equal(result.details.agents[2].agentHandle, "silver-wren-d4e5f6");
		assert.equal(result.details.agents[2].sessionName, "silver-wren-d4e5f6");
		assert.match(result.content[0].text, /amber-fox-a1b2c3/);
		assert.match(result.content[0].text, /mossy-lynx-d4e5f6/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000001/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000003/);
		assert.doesNotMatch(result.content[0].text, /00000000-0000-4000-8000-000000000004/);
		assert.doesNotMatch(result.content[0].text, /private-fallback/);
		assert.match(result.content[0].text, /silver-wren-d4e5f6/);
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

	it("deriveDaemonIdentity prefers BASECAMP_AGENT_TITLE with short session-id suffix", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-xyz";
		process.env.BASECAMP_AGENT_TITLE = "(scout) do thing";
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "0199-aaaa-bbbb-cccc-ddddeeee9f3c" },
			} as any);
			assert.equal(identity.session_name, "(scout) do thing [9f3c]");
			assert.equal(identity.role, "agent");
			assert.match(identity.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity falls back to BASECAMP_SESSION_NAME or node id when BASECAMP_AGENT_TITLE is unset", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentTitle = process.env.BASECAMP_AGENT_TITLE;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;
		const priorSessionName = process.env.BASECAMP_SESSION_NAME;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-fallback";
		delete process.env.BASECAMP_AGENT_TITLE;
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const identity = deriveDaemonIdentity({
				sessionManager: { getSessionId: () => "session-id" },
			} as any);
			assert.equal(identity.session_name, process.env.BASECAMP_SESSION_NAME ?? "agent-fallback");
			assert.match(identity.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentTitle === undefined) delete process.env.BASECAMP_AGENT_TITLE;
			else process.env.BASECAMP_AGENT_TITLE = priorAgentTitle;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
			if (priorSessionName === undefined) delete process.env.BASECAMP_SESSION_NAME;
			else process.env.BASECAMP_SESSION_NAME = priorSessionName;
		}
	});

	it("deriveDaemonIdentity builds a stable canonical handle for top-level sessions", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		delete process.env.BASECAMP_AGENT_DEPTH;
		delete process.env.BASECAMP_AGENT_ID;
		delete process.env.BASECAMP_AGENT_HANDLE;

		try {
			const ctx = { sessionManager: { getSessionId: () => "session-stable-123" } } as any;
			const first = deriveDaemonIdentity(ctx);
			const second = deriveDaemonIdentity(ctx);
			assert.equal(first.role, "session");
			assert.equal(first.agent_handle, second.agent_handle);
			assert.match(first.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
			assert.notEqual(first.agent_handle, "session-stable-123");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity ignores BASECAMP_AGENT_HANDLE for top-level sessions", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		delete process.env.BASECAMP_AGENT_DEPTH;
		delete process.env.BASECAMP_AGENT_ID;
		process.env.BASECAMP_AGENT_HANDLE = "quiet-badger-3dc450";

		try {
			const ctx = { sessionManager: { getSessionId: () => "session-stable-123" } } as any;
			const first = deriveDaemonIdentity(ctx);
			const second = deriveDaemonIdentity(ctx);
			assert.equal(first.role, "session");
			assert.notEqual(first.agent_handle, "quiet-badger-3dc450");
			assert.equal(first.agent_handle, second.agent_handle);
			assert.match(first.agent_handle, /^[a-z]+-[a-z]+-[0-9a-f]{6}$/);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});

	it("deriveDaemonIdentity prefers BASECAMP_AGENT_HANDLE for spawned agents", () => {
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorAgentId = process.env.BASECAMP_AGENT_ID;
		const priorAgentHandle = process.env.BASECAMP_AGENT_HANDLE;

		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.BASECAMP_AGENT_ID = "agent-spawned";
		process.env.BASECAMP_AGENT_HANDLE = "quiet-badger-3dc450";

		try {
			const identity = deriveDaemonIdentity({ sessionManager: { getSessionId: () => "child-session" } } as any);
			assert.equal(identity.role, "agent");
			assert.equal(identity.node_id, "agent-spawned");
			assert.equal(identity.agent_handle, "quiet-badger-3dc450");
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorAgentId === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgentId;
			if (priorAgentHandle === undefined) delete process.env.BASECAMP_AGENT_HANDLE;
			else process.env.BASECAMP_AGENT_HANDLE = priorAgentHandle;
		}
	});
});
