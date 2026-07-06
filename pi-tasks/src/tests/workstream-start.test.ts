import assert from "node:assert/strict";
import * as fs from "node:fs";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { resetSessionProductRoleForTesting, resolveSessionProductRoleOverride } from "pi-core/platform/product-role.ts";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import type { WorkstreamLaunchRecord } from "../workstreams/launch-state.ts";
import { registerWorkstreamStartup, startWorkstream, type WorkstreamStartDeps } from "../workstreams/start.ts";

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
		worktree: { label: "wt-bt/8e95-launch-workstream-too", path: "/worktrees/x", branch: "bt/x" },
		agent: {},
		setup: { status: "succeeded" },
		herdr: { status: "succeeded" },
		launch: { status: "succeeded" },
		createdAt: "2026-07-03T00:00:00.000Z",
		updatedAt: "2026-07-03T00:00:00.000Z",
		...overrides,
	};
}

function makeDeps(overrides: Partial<WorkstreamStartDeps> = {}) {
	const stampCalls: { id: string; handle: string }[] = [];
	const findCalls: { filePath: string; id: string; repo?: string }[] = [];
	let workspace: WorkspaceState | null = { repo: { isRepo: true, name: "org/repo" } } as unknown as WorkspaceState;
	let waitedWorkspace: WorkspaceState | null = workspace;
	let record: WorkstreamLaunchRecord | null = makeRecord();
	let handle: string | null = "swift-otter-1a2b3c";
	const deps: WorkstreamStartDeps = {
		getWorkspaceState: () => workspace,
		waitForWorkspaceState: async () => waitedWorkspace,
		launchStatePath: () => "/tmp/launch-index.json",
		findById: (filePath, id, repo) => {
			findCalls.push({ filePath, id, repo });
			return record;
		},
		stampHandle: (_filePath, id, h) => {
			stampCalls.push({ id, handle: h });
			return record;
		},
		deriveHandle: () => handle,
		...overrides,
	};
	return {
		deps,
		findCalls,
		stampCalls,
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

async function runStart(pi: FakePi, args: string | undefined, ctx: ExtensionContext, deps: WorkstreamStartDeps) {
	await startWorkstream(args, pi as unknown as ExtensionAPI, ctx, deps);
}

describe("workstream startup", () => {
	afterEach(resetSessionProductRoleForTesting);

	it("loads the brief, injects it, and stamps this session's handle", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(pi.userMessages[0]!, /Launch Workstream Too/);
		assert.match(pi.userMessages[0]!, /registered as `swift-otter-1a2b3c`/);
		assert.deepEqual(harness.findCalls, [
			{ filePath: "/tmp/launch-index.json", id: "launch-workstream-too", repo: "org/repo" },
		]);
		assert.deepEqual(harness.stampCalls, [{ id: "launch-workstream-too", handle: "swift-otter-1a2b3c" }]);
	});

	it("trims ids before lookup", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		await runStart(pi, "  launch-workstream-too  ", ctx, harness.deps);

		assert.equal(harness.findCalls[0]?.id, "launch-workstream-too");
	});

	it("returns a usage error when no id is given", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx, notices } = makeCtx();

		await runStart(pi, "  ", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Usage: pi --workstream <id>/);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports a clear error for an unknown id without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setRecord(null);
		const { ctx, notices } = makeCtx();

		await runStart(pi, "missing-id", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /No staged workstream "missing-id"/);
		assert.equal(notices[0]?.level, "error");
	});

	it("fails closed when the repository workspace cannot be determined", async () => {
		const pi = new FakePi();
		let findCalled = false;
		const harness = makeDeps({
			getWorkspaceState: () => null,
			waitForWorkspaceState: async () => null,
			findById: () => {
				findCalled = true;
				return makeRecord();
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.equal(findCalled, false);
		assert.match(notices[0]?.message ?? "", /not in a repository workspace/);
		assert.equal(notices[0]?.level, "error");
	});

	it("waits for workspace state during startup before lookup", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setWorkspace(null);
		harness.setWaitedWorkspace({ repo: { isRepo: true, name: "org/repo" } } as unknown as WorkspaceState);
		const { ctx } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.equal(harness.findCalls[0]?.repo, "org/repo");
	});

	it("reports workspace lookup errors without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			getWorkspaceState: () => {
				throw new Error("workspace state unavailable");
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Could not load staged workstream "launch-workstream-too"/);
		assert.match(notices[0]?.message ?? "", /workspace state unavailable/);
		assert.equal(notices[0]?.level, "error");
	});

	it("reports launch-state lookup errors without injecting or stamping", async () => {
		const pi = new FakePi();
		const harness = makeDeps({
			findById: () => {
				throw new Error("launch index corrupt");
			},
		});
		const { ctx, notices } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.stampCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /Could not load staged workstream "launch-workstream-too"/);
		assert.match(notices[0]?.message ?? "", /launch index corrupt/);
		assert.equal(notices[0]?.level, "error");
	});

	it("degrades gracefully when the handle cannot be derived", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		harness.setHandle(null);
		const { ctx } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

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

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

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

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

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
		harness.setRecord(makeRecord({ worktree: { label: "wt-bt/no-path", branch: "bt/no-path" } }));
		const { ctx } = makeCtx();

		await runStart(pi, "launch-workstream-too", ctx, harness.deps);

		assert.equal(pi.userMessages.length, 1);
		assert.match(pi.userMessages[0]!, /Worktree path: not recorded in launch record/);
		assert.doesNotMatch(pi.userMessages[0]!, /Worktree path:\s*\n/);
	});

	it("registers a string startup flag and starts the workstream on session_start", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		pi.setFlag("workstream", "launch-workstream-too");
		await pi.emitSessionStart(ctx);

		assert.deepEqual(pi.flags.get("workstream"), {
			description: "Start a staged workstream by id on session startup",
			type: "string",
		});
		assert.equal(pi.userMessages.length, 1);
		assert.deepEqual(harness.stampCalls, [{ id: "launch-workstream-too", handle: "swift-otter-1a2b3c" }]);
	});

	it("registers a product-role provider for non-empty --workstream sessions", () => {
		const pi = new FakePi();
		const harness = makeDeps();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		assert.equal(resolveSessionProductRoleOverride(), null);

		pi.setFlag("workstream", "   ");
		assert.equal(resolveSessionProductRoleOverride(), null);

		pi.setFlag("workstream", "launch-workstream-too");
		assert.equal(resolveSessionProductRoleOverride(), "workstream_agent");
	});

	it("does nothing on session_start when --workstream is absent", async () => {
		const pi = new FakePi();
		const harness = makeDeps();
		const { ctx } = makeCtx();

		registerWorkstreamStartup(pi as unknown as ExtensionAPI, harness.deps);
		await pi.emitSessionStart(ctx);

		assert.equal(pi.userMessages.length, 0);
		assert.equal(harness.findCalls.length, 0);
		assert.equal(harness.stampCalls.length, 0);
	});

	it("is wired from pi-tasks/index.ts", () => {
		const indexSource = fs.readFileSync(new URL("../../index.ts", import.meta.url), "utf8");
		assert.match(indexSource, /import \{ registerWorkstreamStartup \} from "\.\/src\/workstreams\/start\.ts";/);
		assert.match(indexSource, /registerWorkstreamStartup\(pi\);/);
	});
});
