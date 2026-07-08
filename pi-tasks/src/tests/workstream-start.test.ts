import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { resetSessionProductRoleForTesting, resolveSessionProductRoleOverride } from "pi-core/platform/product-role.ts";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { getAgentMode, resetAgentMode } from "pi-core/session/agent-mode.ts";
import {
	getCurrentSessionState,
	initializeCurrentSessionState,
	resetCurrentSessionState,
} from "pi-core/state/index.ts";
import type { WorkstreamLaunchRecord } from "../workstreams/launch-state.ts";
import {
	defaultWorkstreamStartDeps,
	registerWorkstreamStartup,
	startWorkstream,
	type WorkstreamStartDeps,
} from "../workstreams/start.ts";

type SessionStartHandler = (event: SessionStartEvent, ctx: ExtensionContext) => Promise<void>;

class FakePi {
	readonly flags = new Map<string, { description: string; type: string }>();
	readonly userMessages: string[] = [];
	private readonly flagValues = new Map<string, unknown>();
	private sessionStart: SessionStartHandler | null = null;

	registerFlag(name: string, flag: { description: string; type: string }): void {
		this.flags.set(name, flag);
	}

	getFlag(name: string): unknown {
		return this.flagValues.get(name);
	}

	setFlag(name: string, value: unknown): void {
		this.flagValues.set(name, value);
	}

	on(event: string, handler: SessionStartHandler): void {
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

function makeRecord(overrides: Partial<WorkstreamLaunchRecord> = {}): WorkstreamLaunchRecord {
	return {
		id: "launch-workstream-too",
		fingerprint: "fp",
		repo: "org/repo",
		source: { dossierPath: "/graph/pages/Dossier.md", repoPagePath: "/graph/pages/Repo.md" },
		workstream: {
			label: "Launch Workstream Too",
			brief: "Implement the launch workstream tool.",
			constraints: "Stay in scope.",
		},
		worktree: { label: "copilot/steady-amber-otter", path: "/worktrees/x", branch: "bt/x" },
		agent: {},
		setup: { status: "succeeded" },
		herdr: { status: "succeeded" },
		launch: { status: "succeeded" },
		createdAt: "2026-07-03T00:00:00.000Z",
		updatedAt: "2026-07-03T00:00:00.000Z",
		...overrides,
	};
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

function makeDeps(overrides: Partial<WorkstreamStartDeps> = {}) {
	const stampCalls: { id: string; handle: string }[] = [];
	const findByWorktreeLabelCalls: { filePath: string; worktreeLabel: string; repo?: string }[] = [];
	const enterExploreModeCalls: { event: SessionStartEvent; ctx: ExtensionContext }[] = [];
	let workspace: WorkspaceState | null = makeWorkspace();
	let waitedWorkspace: WorkspaceState | null = workspace;
	let record: WorkstreamLaunchRecord | null = makeRecord();
	let handle: string | null = "swift-otter-1a2b3c";
	const deps: WorkstreamStartDeps = {
		getWorkspaceState: () => workspace,
		waitForWorkspaceState: async () => waitedWorkspace,
		launchStatePath: () => "/tmp/launch-index.json",
		findByWorktreeLabel: (filePath, worktreeLabel, repo) => {
			findByWorktreeLabelCalls.push({ filePath, worktreeLabel, repo });
			return record?.worktree.label === worktreeLabel && (!repo || record.repo === repo) ? record : null;
		},
		stampHandle: (_filePath, id, h) => {
			stampCalls.push({ id, handle: h });
			return record;
		},
		deriveHandle: () => handle,
		enterExploreMode: (event, ctx) => {
			enterExploreModeCalls.push({ event, ctx });
		},
		...overrides,
	};
	return {
		deps,
		findByWorktreeLabelCalls,
		stampCalls,
		enterExploreModeCalls,
		setRecord(value: WorkstreamLaunchRecord | null) {
			record = value;
		},
		setHandle(value: string | null) {
			handle = value;
		},
		setWorkspace(value: WorkspaceState | null) {
			workspace = value;
		},
		setWaitedWorkspace(value: WorkspaceState | null) {
			waitedWorkspace = value;
		},
	};
}

async function runStart(pi: FakePi, ctx: ExtensionContext, deps: WorkstreamStartDeps) {
	await startWorkstream(pi as unknown as ExtensionAPI, ctx, deps);
}

describe("workstream startup", () => {
	afterEach(resetSessionProductRoleForTesting);

	it("loads the brief, injects it, and stamps this session's handle", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(pi.userMessages[0]!, /Launch Workstream Too/);
		assert.match(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.deepEqual(harness.findByWorktreeLabelCalls, [
			{ filePath: "/tmp/launch-index.json", worktreeLabel: "copilot/steady-amber-otter", repo: "org/repo" },
		]);
		assert.deepEqual(harness.stampCalls, [{ id: "launch-workstream-too", handle: "swift-otter-1a2b3c" }]);
	});

	it("infers a bare --workstream launch from the active worktree label", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /copilot\/steady-amber-otter/);
		assert.deepEqual(harness.findByWorktreeLabelCalls, [
			{ filePath: "/tmp/launch-index.json", worktreeLabel: "copilot/steady-amber-otter", repo: "org/repo" },
		]);
	});

	it("reports an error for a bare --workstream launch without an active worktree", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setWorkspace(makeWorkspace({ activeWorktree: null }));
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.findByWorktreeLabelCalls.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.equal(
			notices[0]?.message,
			"Run `pi --workstream` from inside the workstream worktree Herdr set up; this session is not in a worktree.",
		);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports an error when bare --workstream does not match a staged workstream", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setRecord(null);
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.deepEqual(harness.findByWorktreeLabelCalls, [
			{ filePath: "/tmp/launch-index.json", worktreeLabel: "copilot/steady-amber-otter", repo: "org/repo" },
		]);
		assert.match(notices[0]?.message ?? "", /No staged workstream found for worktree "copilot\/steady-amber-otter"/);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports a clear error when the worktree has no staged record without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setRecord(null);
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /No staged workstream found for worktree "copilot\/steady-amber-otter"/);
		assert.equal(notices[0]?.level, "error");
	});

	it("fails closed when the repository workspace cannot be determined", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setWorkspace(null);
		harness.setWaitedWorkspace(null);
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.equal(harness.findByWorktreeLabelCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not in a repository workspace/);
		assert.equal(notices[0]?.level, "error");
	});

	it("waits for workspace state during startup before lookup", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setWorkspace(null);
		harness.setWaitedWorkspace(makeWorkspace());
		const { ctx } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.equal(harness.findByWorktreeLabelCalls[0]?.repo, "org/repo");
	});

	it("reports workspace lookup errors without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			getWorkspaceState: () => {
				throw new Error("workspace state unavailable");
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Could not load the staged workstream for this worktree:/);
		assert.match(notices[0]?.message ?? "", /workspace state unavailable/);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports launch-state lookup errors without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			findByWorktreeLabel: () => {
				throw new Error("launch index corrupt");
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Could not load the staged workstream for this worktree:/);
		assert.match(notices[0]?.message ?? "", /launch index corrupt/);
		assert.equal(notices[0]?.level, "error");
	});

	it("degrades gracefully when the handle cannot be derived", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setHandle(null);
		const { ctx } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(pi.userMessages[0]!, /agent handle could not be determined/);
		assert.equal(harness.stampCalls.length, 0);
	});

	it("warns when the handle is derived but cannot be persisted", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			stampHandle: () => {
				throw new Error("disk full");
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /agent handle was derived as `swift-otter-1a2b3c`/);
		assert.match(pi.userMessages[0]!, /could not be persisted/);
		assert.doesNotMatch(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.doesNotMatch(pi.userMessages[0]!, /agent handle could not be determined/);
		assert.match(notices[0]?.message ?? "", /could not persist it to the workstream record/);
		assert.equal(notices[0]?.level, "error");
		assert.equal(harness.stampCalls.length, 0);
	});

	it("warns when handle stamping returns null without throwing", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			stampHandle: () => null,
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /agent handle was derived as `swift-otter-1a2b3c`/);
		assert.match(pi.userMessages[0]!, /could not be persisted/);
		assert.doesNotMatch(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.match(notices[0]?.message ?? "", /could not persist it to the workstream record/);
		assert.equal(notices[0]?.level, "error");
		assert.equal(harness.stampCalls.length, 0);
	});

	it("uses an explicit worktree path fallback when the launch record has no path", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setRecord(makeRecord({ worktree: { label: "copilot/steady-amber-otter", branch: "bt/no-path" } }));
		const { ctx } = makeCtx();

		await runStart(pi, ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /Worktree path: not recorded in launch record/);
		assert.doesNotMatch(pi.userMessages[0]!, /Worktree path:\s*\n/);
	});

	it("registers a boolean startup flag and starts the workstream on session_start", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		pi.setFlag("workstream", true);
		await pi.emitSessionStart(ctx);

		assert.deepEqual(pi.flags.get("workstream"), {
			description: "Start the staged workstream for the current worktree (run bare inside the worktree Herdr set up).",
			type: "boolean",
		});
		assert.equal(pi.userMessages.length, 1);
		assert.deepEqual(harness.stampCalls, [{ id: "launch-workstream-too", handle: "swift-otter-1a2b3c" }]);
		assert.equal(harness.enterExploreModeCalls.length, 1);
		assert.equal(harness.enterExploreModeCalls[0]?.event.reason, "new");
		assert.equal(harness.enterExploreModeCalls[0]?.ctx, ctx);
	});

	it("registers a product-role provider for any present --workstream flag", () => {
		const pi = new FakePi();
		const harness = makeDeps();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		assert.equal(resolveSessionProductRoleOverride(), null);

		pi.setFlag("workstream", true);
		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");

		pi.setFlag("workstream", undefined);
		assert.equal(resolveSessionProductRoleOverride(), null);
	});

	it("does nothing on session_start when --workstream is absent", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.findByWorktreeLabelCalls.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.equal(harness.enterExploreModeCalls.length, 0);
	});

	it("enters Explore mode for a present --workstream flag and then infers the workstream", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		pi.setFlag("workstream", true);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 1);
		assert.equal(harness.findByWorktreeLabelCalls.length, 1);
		assert.equal(harness.stampCalls.length, 1);
		assert.equal(harness.enterExploreModeCalls.length, 1);
	});

	it("is wired from pi-tasks/index.ts", () => {
		const indexSource = fs.readFileSync(new URL("../../index.ts", import.meta.url), "utf8");
		assert.match(indexSource, /import \{ registerWorkstreamStartup \} from "\.\/src\/workstreams\/start\.ts";/);
		assert.match(indexSource, /registerWorkstreamStartup\(pi\);/);
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
		// Pre-initialize with a temp state dir so the real enterExploreMode reuses it (matching session identity)
		// instead of writing to the default state dir.
		initializeCurrentSessionState(ctx, stateDir);

		defaultWorkstreamStartDeps().enterExploreMode({ type: "session_start", reason: "new" } as SessionStartEvent, ctx);

		assert.equal(getAgentMode(), "planning");
		assert.equal(getCurrentSessionState().agentMode, "planning");
	});
});
