import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { resetSessionProductRoleForTesting } from "#core/platform/product-role.ts";
import type { WorkspaceState, WorkspaceWorktree } from "#core/platform/workspace.ts";
import type { DaemonClient, WorkstreamDetail } from "../../agents/daemon/client.ts";
import { startWorkstream, type WorkstreamStartDeps } from "../start.ts";

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
