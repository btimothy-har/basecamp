import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { resetSessionProductRoleForTesting, resolveSessionProductRoleOverride } from "#core/platform/product-role.ts";
import type { WorkspaceState, WorkspaceWorktree } from "#core/platform/workspace.ts";
import { getAgentMode, resetAgentMode } from "#core/session/agent-mode.ts";
import { resetCopilotLaunchForTesting, setCopilotLaunchReader } from "#core/session/copilot-launch.ts";
import { getCurrentSessionState, initializeCurrentSessionState, resetCurrentSessionState } from "#core/state/index.ts";
import type { DaemonClient, WorkstreamDetail } from "../../agents/daemon/client.ts";
import {
	defaultWorkstreamStartDeps,
	parseWorkstreamFlagValue,
	registerWorkstreamStartup,
	startWorkstream,
	type WorkstreamStartDeps,
} from "../start.ts";

function makeWorkstreamDetail(overrides: Partial<WorkstreamDetail> = {}): WorkstreamDetail {
	return {
		id: "ws-uuid-1",
		slug: "steady-amber-otter",
		label: "Launch Workstream Too",
		brief: "Implement the launch workstream tool.",
		constraints: null,
		source_dossier_path: "/graph/pages/Dossier.md",
		source_repo_page_path: null,
		status: "open",
		created_at: "2026-07-03T00:00:00.000Z",
		updated_at: "2026-07-03T00:00:00.000Z",
		agent_count: 0,
		agents: [],
		...overrides,
	};
}

class FakeDaemonClient {
	readonly attachCalls: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}[] = [];
	private attachStatus: "attached" | "not_found" | "error" = "attached";
	private attachError: Error | null = null;

	setAttachStatus(status: "attached" | "not_found" | "error"): void {
		this.attachStatus = status;
	}
	setAttachThrow(err: Error): void {
		this.attachError = err;
	}

	async attachWorkstreamAgent(input: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}) {
		this.attachCalls.push(input);
		if (this.attachError) throw this.attachError;
		return { status: this.attachStatus, error: this.attachStatus === "error" ? "db error" : null };
	}
}

function makeWorkspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		repo: { isRepo: true, name: "org/repo" },
		activeWorktree: {
			label: "copilot/steady-amber-otter",
			path: "/worktrees/org/repo/copilot/steady-amber-otter",
			branch: "bt/x",
			created: false,
		},
		...overrides,
	} as unknown as WorkspaceState;
}

function makeCtx(): { ctx: ExtensionContext; notices: { message: string; level: string }[] } {
	const notices: { message: string; level: string }[] = [];
	const ctx = {
		hasUI: true,
		cwd: "/repo",
		ui: {
			notify(message: string, level: string) {
				notices.push({ message, level });
			},
		},
		sessionManager: { getSessionId: () => "session-abc" },
	} as unknown as ExtensionContext;
	return { ctx, notices };
}

function makeDeps(client: FakeDaemonClient, overrides: Partial<WorkstreamStartDeps> = {}) {
	const enterExploreModeCalls: { event: SessionStartEvent; ctx: ExtensionContext }[] = [];
	let workspace: WorkspaceState | null = makeWorkspace();
	let waitedWorkspace: WorkspaceState | null = workspace;
	const workstreamDetails = new Map<string, WorkstreamDetail | null>();
	let detail: WorkstreamDetail | null = makeWorkstreamDetail();

	const deps: WorkstreamStartDeps = {
		getWorkspaceState: () => workspace,
		waitForWorkspaceState: async () => waitedWorkspace,
		resolveSocketPath: () => "/tmp/daemon.sock",
		getWorkstreamDetail: async (_sp, identifier) => {
			if (workstreamDetails.has(identifier)) return workstreamDetails.get(identifier) ?? null;
			if (detail && (detail.slug === identifier || detail.id === identifier)) return detail;
			return null;
		},
		getClient: async () => client as unknown as DaemonClient,
		enterExploreMode: (event, ctx) => {
			enterExploreModeCalls.push({ event, ctx });
		},
		...overrides,
	};

	return {
		deps,
		client,
		enterExploreModeCalls,
		setWorkspace(value: WorkspaceState | null) {
			workspace = value;
		},
		setWaitedWorkspace(value: WorkspaceState | null) {
			waitedWorkspace = value;
		},
		setDetail(value: WorkstreamDetail | null) {
			detail = value;
		},
		setWorkstreamDetail(identifier: string, value: WorkstreamDetail | null) {
			workstreamDetails.set(identifier, value);
		},
	};
}

async function runStart(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	flagValue: string | undefined,
	deps: WorkstreamStartDeps,
) {
	await startWorkstream(pi, ctx, flagValue, deps);
}

class FakePi {
	readonly flags = new Map<string, { description: string; type: string }>();
	readonly userMessages: string[] = [];
	private readonly flagValues = new Map<string, unknown>();
	private sessionStart: ((event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>) | null = null;

	registerFlag(name: string, flag: { description: string; type: string }): void {
		this.flags.set(name, flag);
	}

	getFlag(name: string): unknown {
		return this.flagValues.get(name);
	}

	setFlag(name: string, value: unknown): void {
		this.flagValues.set(name, value);
	}

	on(event: string, handler: (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>): void {
		if (event === "session_start") this.sessionStart = handler;
	}

	sendUserMessage(text: string): void {
		this.userMessages.push(text);
	}

	async emitSessionStart(ctx: ExtensionContext): Promise<void> {
		assert.ok(this.sessionStart, "session_start handler should be registered");
		await this.sessionStart({ type: "session_start", reason: "new" } as SessionStartEvent, ctx);
	}
}

describe("workstream startup (daemon-backed)", () => {
	afterEach(resetSessionProductRoleForTesting);

	it("infers the workstream from the copilot/<slug> worktree label and attaches + injects the brief", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(piMessages[0]!, /Launch Workstream Too/);
		assert.match(piMessages[0]!, /attached to the workstream/);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "steady-amber-otter");
		assert.equal(client.attachCalls[0]?.repo, "org/repo");
		assert.equal(client.attachCalls[0]?.worktreeLabel, "copilot/steady-amber-otter");
		assert.equal(client.attachCalls[0]?.status, "attached");
	});

	it("resolves an explicit --workstream=<slug> and attaches", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(makeWorkstreamDetail({ slug: "explicit-slug", id: "ws-explicit" }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, "explicit-slug", harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /# Herdr workstream launch brief/);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "explicit-slug");
	});

	it("resolves an explicit --workstream=<id> and attaches", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(makeWorkstreamDetail({ slug: "id-slug", id: "ws-id-123" }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, "ws-id-123", harness.deps);

		assert.equal(piMessages.length, 1);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "ws-id-123");
	});

	it("appends agents — a second attach call adds a second agent entry", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);
		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(client.attachCalls.length, 2, "attach should append, not overwrite");
		assert.equal(client.attachCalls[0]?.workstream, "steady-amber-otter");
		assert.equal(client.attachCalls[1]?.workstream, "steady-amber-otter");
		assert.equal(piMessages.length, 2);
	});

	it("notifies without blocking when attach fails, but still injects the brief", async () => {
		const client = new FakeDaemonClient();
		client.setAttachStatus("error");
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1, "brief should still be injected");
		assert.match(piMessages[0]!, /attach to the daemon failed/);
		assert.match(notices[0]?.message ?? "", /attach/i);
	});

	it("notifies when the workstream is not found on attach but still injects the brief", async () => {
		const client = new FakeDaemonClient();
		client.setAttachStatus("not_found");
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /did not find workstream/);
		assert.match(notices[0]?.message ?? "", /not found/i);
	});

	it("reports an error for a bare --workstream without an active worktree", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(makeWorkspace({ activeWorktree: null }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not in a worktree/);
	});

	it("reports an error when the worktree label is not a copilot/<slug> worktree and no explicit flag is given", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(
			makeWorkspace({
				activeWorktree: {
					kind: "git-worktree",
					label: "wt-bt/other",
					path: "/w",
					branch: "bt/o",
					created: false,
				} as WorkspaceWorktree,
			}),
		);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not a copilot/);
	});

	it("reports an error when the workstream cannot be resolved from the daemon", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(null);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /No workstream found/);
	});

	it("fails closed when the repository workspace cannot be determined", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(null);
		harness.setWaitedWorkspace(null);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not in a repository workspace/);
	});
});

describe("registerWorkstreamStartup", () => {
	afterEach(() => {
		resetSessionProductRoleForTesting();
		resetCopilotLaunchForTesting();
	});

	it("registers a boolean startup flag", () => {
		const pi = new FakePi();
		const harness = makeDeps(new FakeDaemonClient());

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);

		assert.deepEqual(pi.flags.get("workstream"), {
			description:
				"Start the workstream for the current worktree. Bare --workstream infers the workstream from the copilot/<slug> worktree label; --workstream=<slug|id> resolves explicitly.",
			type: "boolean",
		});
	});

	it("registers a product-role provider for any present --workstream flag", () => {
		const pi = new FakePi();
		const harness = makeDeps(new FakeDaemonClient());

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		assert.equal(resolveSessionProductRoleOverride(), null);

		pi.setFlag("workstream", true);
		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");

		// --copilot takes precedence: role resolves to null while copilot is launched
		setCopilotLaunchReader(() => true);
		assert.equal(resolveSessionProductRoleOverride(), null);
		setCopilotLaunchReader(() => false);
		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");

		pi.setFlag("workstream", undefined);
		assert.equal(resolveSessionProductRoleOverride(), null);
	});

	it("copilot takes precedence over --workstream on session_start", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		const pi = new FakePi();
		const { ctx, notices } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		pi.setFlag("workstream", true);
		setCopilotLaunchReader(() => true);
		await pi.emitSessionStart(ctx);

		assert.equal(harness.enterExploreModeCalls.length, 0);
		assert.equal(pi.userMessages.length, 0);
		assert.equal(notices.length, 1);
		assert.equal(notices[0]?.level, "warning");
		assert.match(notices[0]?.message ?? "", /copilot takes precedence/);
	});

	it("enters Explore mode and starts the workstream on session_start when the flag is present", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const pi = new FakePi();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		pi.setFlag("workstream", true);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.equal(harness.enterExploreModeCalls.length, 1);
		assert.equal(harness.enterExploreModeCalls[0]?.event.reason, "new");
		assert.equal(client.attachCalls.length, 1);
	});

	it("does nothing on session_start when --workstream is absent", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const pi = new FakePi();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, async () => null, harness.deps);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.enterExploreModeCalls.length, 0);
		assert.equal(client.attachCalls.length, 0);
	});
});

describe("defaultWorkstreamStartDeps enterExploreMode", () => {
	it("initializes session state and forces planning (Explore) mode", (t) => {
		const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-workstream-mode-"));
		t.after(() => {
			resetCurrentSessionState();
			resetAgentMode();
			fs.rmSync(stateDir, { recursive: true, force: true });
		});

		const ctx = {
			hasUI: true,
			ui: { notify() {} },
			sessionManager: { getSessionId: () => "ws-mode-session", getSessionFile: () => null },
		} as unknown as ExtensionContext;
		initializeCurrentSessionState(ctx, stateDir);

		defaultWorkstreamStartDeps(async () => null).enterExploreMode(
			{ type: "session_start", reason: "new" } as SessionStartEvent,
			ctx,
		);

		assert.equal(getAgentMode(), "planning");
		assert.equal(getCurrentSessionState().agentMode, "planning");
	});
});

describe("parseWorkstreamFlagValue", () => {
	it("returns undefined for a bare --workstream", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--workstream"]), undefined);
	});

	it("recovers an explicit --workstream=<value>", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--workstream=my-slug"]), "my-slug");
		assert.equal(parseWorkstreamFlagValue(["--workstream=ws_abc123"]), "ws_abc123");
	});

	it("treats an empty or whitespace value as infer (undefined)", () => {
		assert.equal(parseWorkstreamFlagValue(["--workstream="]), undefined);
		assert.equal(parseWorkstreamFlagValue(["--workstream=   "]), undefined);
	});

	it("returns undefined when no --workstream arg is present", () => {
		assert.equal(parseWorkstreamFlagValue(["node", "pi", "--other=1"]), undefined);
	});
});
