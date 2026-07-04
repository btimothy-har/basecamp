import assert from "node:assert/strict";
import * as fs from "node:fs";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState, WorkspaceWorktree } from "pi-core/platform/workspace.ts";
import type { WorktreeResult } from "pi-core/workspace/worktree.ts";
import type { WorkstreamLaunchRecord, WorkstreamLaunchRecordUpdate } from "../workstreams/launch-state.ts";
import {
	executeLaunchWorkstream,
	type LaunchWorkstreamDeps,
	type LaunchWorkstreamResultDetails,
	registerWorkstreamTools,
} from "../workstreams/tools.ts";

type RegisteredToolResult = {
	content: { type: "text"; text: string }[];
	details?: unknown;
	isError?: boolean;
};

interface RegisteredTool {
	name: string;
	execute(
		toolCallId: string,
		params: Record<string, unknown>,
		signal?: AbortSignal,
		onUpdate?: unknown,
		ctx?: ExtensionContext,
	): Promise<RegisteredToolResult>;
}

class FakePi {
	readonly tools = new Map<string, RegisteredTool>();
	readonly commands = new Map<string, unknown>();
	readonly handlers = new Map<string, unknown[]>();

	registerTool(tool: RegisteredTool): void {
		this.tools.set(tool.name, tool);
	}

	registerCommand(name: string, command: unknown): void {
		this.commands.set(name, command);
	}

	on(eventName: string, handler: unknown): void {
		const handlers = this.handlers.get(eventName) ?? [];
		handlers.push(handler);
		this.handlers.set(eventName, handlers);
	}

	sendMessage(): void {}
	sendUserMessage(): void {}

	async exec(): Promise<{ code: number; stdout: string; stderr: string; killed: boolean }> {
		return { code: 0, stdout: "", stderr: "", killed: false };
	}
}

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}

class FakeStore {
	readonly records: WorkstreamLaunchRecord[] = [];
	readonly appendCalls: WorkstreamLaunchRecord[] = [];
	readonly updateCalls: { id: string; updates: WorkstreamLaunchRecordUpdate }[] = [];
	path = "/tmp/workstream-launch-index.json";
	duplicateOverride: WorkstreamLaunchRecord | null | undefined;

	launchStatePath(): string {
		return this.path;
	}

	nextAvailableId(_filePath: string, repo: string, label: string): string {
		const base =
			label
				.trim()
				.toLowerCase()
				.replace(/[^a-z0-9]+/g, "-")
				.replace(/^-+|-+$/g, "") || "workstream";
		const taken = new Set(this.records.filter((record) => record.repo === repo).map((record) => record.id));
		if (!taken.has(base)) return base;
		for (let suffix = 2; ; suffix += 1) {
			const candidate = `${base}-${suffix}`;
			if (!taken.has(candidate)) return candidate;
		}
	}

	appendRecordIfAbsent(
		_filePath: string,
		record: WorkstreamLaunchRecord,
		lookup: { repo?: string; fingerprint?: string; worktreeLabel?: string },
	) {
		const duplicate = this.matchDuplicate(lookup);
		if (duplicate)
			return { appended: false, record: duplicate, state: { version: 1 as const, records: clone(this.records) } };
		this.appendCalls.push(clone(record));
		this.records.push(clone(record));
		return { appended: true, record: clone(record), state: { version: 1 as const, records: clone(this.records) } };
	}

	updateRecord(
		_filePath: string,
		id: string,
		updates: WorkstreamLaunchRecordUpdate,
		now = "2026-07-03T00:00:01.000Z",
	): WorkstreamLaunchRecord | null {
		this.updateCalls.push({ id, updates: clone(updates) });
		const index = this.records.findIndex((record) => record.id === id);
		if (index === -1) return null;
		const current = this.records[index]!;
		const updated: WorkstreamLaunchRecord = {
			...current,
			...updates,
			source: updates.source ? { ...current.source, ...updates.source } : current.source,
			workstream: updates.workstream ? { ...current.workstream, ...updates.workstream } : current.workstream,
			worktree: updates.worktree ? { ...current.worktree, ...updates.worktree } : current.worktree,
			agent: updates.agent ? { ...current.agent, ...updates.agent } : current.agent,
			setup: updates.setup ?? current.setup,
			herdr: updates.herdr ?? current.herdr,
			launch: updates.launch ?? current.launch,
			createdAt: current.createdAt,
			updatedAt: updates.updatedAt ?? now,
		};
		this.records[index] = clone(updated);
		return clone(updated);
	}

	private matchDuplicate(lookup: {
		repo?: string;
		fingerprint?: string;
		worktreeLabel?: string;
	}): WorkstreamLaunchRecord | null {
		return (
			this.records.find((record) => {
				if (lookup.repo && record.repo !== lookup.repo) return false;
				if (lookup.fingerprint && record.fingerprint === lookup.fingerprint) return true;
				if (lookup.worktreeLabel && record.worktree.label === lookup.worktreeLabel) return true;
				return false;
			}) ?? null
		);
	}

	findDuplicate(
		_filePath: string,
		lookup: { repo?: string; fingerprint?: string; worktreeLabel?: string },
	): WorkstreamLaunchRecord | null {
		if (this.duplicateOverride !== undefined) return this.duplicateOverride;
		return this.matchDuplicate(lookup);
	}
}

function makeWorkspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: "/repo",
		scratchDir: "/tmp/pi/basecamp",
		repo: {
			isRepo: true,
			name: "org/repo",
			root: "/repo",
			remoteUrl: "git@github.com:org/repo.git",
		},
		protectedRoot: "/repo",
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

function makeContext(): ExtensionContext {
	return {
		hasUI: true,
		sessionManager: {
			getSessionId() {
				return "018ff5a0-2222-7333-8444-000000008e95";
			},
		},
	} as unknown as ExtensionContext;
}

function baseParams(overrides: Record<string, unknown> = {}) {
	return {
		source: {
			dossierPath: "/graph/pages/Dossier.md",
			repoPagePath: "/graph/pages/Repo.md",
		},
		workstream: {
			label: "Launch Workstream Too",
			brief: "Implement the launch workstream tool.",
			constraints: "Stay in scope.",
		},
		...overrides,
	};
}

function makeDeps(overrides: Partial<LaunchWorkstreamDeps> = {}) {
	const store = new FakeStore();
	const provisionCalls: { repoRoot: string; repoName: string; label: string; branchName: string | null }[] = [];
	const setupCalls: { command: string; worktreeDir: string; repoRoot: string }[] = [];
	const herdrCalls: { workspace: unknown; worktree: { path: string; label: string } }[] = [];
	let workspace = makeWorkspace();
	let listedWorktrees: WorkspaceWorktree[] = [];
	let setupCommand: string | null = null;
	let created = true;
	let provision: LaunchWorkstreamDeps["getOrCreateWorktree"] = async (_pi, repoRoot, repoName, label, branchName) => {
		provisionCalls.push({ repoRoot, repoName, label, branchName });
		return {
			worktreeDir: `/worktrees/org/repo/${label}`,
			label,
			branch: branchName ?? `${label}`,
			created,
		} satisfies WorktreeResult;
	};
	let setupResult = { ran: true, exitCode: 0, timedOut: false, stderrTail: "" };
	let herdrResult: Awaited<ReturnType<LaunchWorkstreamDeps["openWorkstreamInHerdr"]>> = {
		status: "opened",
		message: "Herdr workstream opened.",
		args: [],
	};
	let nowCounter = 0;

	const deps: LaunchWorkstreamDeps = {
		getWorkspaceState: () => workspace,
		listWorkspaceWorktrees: async () => listedWorktrees,
		getOrCreateWorktree: (pi, repoRoot, repoName, label, branchName) =>
			provision(pi, repoRoot, repoName, label, branchName),
		readWorktreeSetupCommand: () => setupCommand,
		runWorktreeSetup: async (_pi, opts) => {
			setupCalls.push(opts);
			return setupResult;
		},
		openWorkstreamInHerdr: async (_pi, herdrWorkspace, worktree) => {
			herdrCalls.push({ workspace: herdrWorkspace, worktree });
			return herdrResult;
		},
		store,
		now: () => `2026-07-03T00:00:0${nowCounter++}.000Z`,
		...overrides,
	};

	return {
		deps,
		store,
		provisionCalls,
		setupCalls,
		herdrCalls,
		setWorkspace(value: WorkspaceState | null) {
			workspace = value as WorkspaceState;
		},
		setListedWorktrees(value: WorkspaceWorktree[]) {
			listedWorktrees = value;
		},
		setSetupCommand(value: string | null) {
			setupCommand = value;
		},
		setCreated(value: boolean) {
			created = value;
		},
		setProvision(value: LaunchWorkstreamDeps["getOrCreateWorktree"]) {
			provision = value;
		},
		setSetupResult(value: typeof setupResult) {
			setupResult = value;
		},
		setHerdrResult(value: typeof herdrResult) {
			herdrResult = value;
		},
	};
}

async function runLaunch(params: unknown, deps: LaunchWorkstreamDeps) {
	const pi = new FakePi() as unknown as ExtensionAPI;
	const result = await executeLaunchWorkstream(params, pi, makeContext(), undefined, deps);
	return { result, details: result.details as LaunchWorkstreamResultDetails };
}

// The derived worktree label prefix comes from process.env.USER; pin it so the
// expected `wt-bt/...` labels are deterministic regardless of the host/CI user.
let savedUser: string | undefined;
beforeEach(() => {
	savedUser = process.env.USER;
	process.env.USER = "btimothyhar";
});
afterEach(() => {
	if (savedUser === undefined) delete process.env.USER;
	else process.env.USER = savedUser;
});

describe("launch_workstream validation and registration", () => {
	it("validates non-empty required input at the execution boundary", async () => {
		const harness = makeDeps();
		const { result, details } = await runLaunch(baseParams({ source: { dossierPath: " " } }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /source\.dossierPath/);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("registers launch_workstream directly and wires registration from pi-tasks/index.ts", () => {
		const directPi = new FakePi();
		registerWorkstreamTools(directPi as unknown as ExtensionAPI, makeDeps().deps);
		assert.ok(directPi.tools.has("launch_workstream"));

		const indexSource = fs.readFileSync(new URL("../../index.ts", import.meta.url), "utf8");
		assert.match(indexSource, /import \{ registerWorkstreamTools \} from "\.\/src\/workstreams\/tools\.ts";/);
		assert.match(indexSource, /registerWorkstreamTools\(pi\);/);
	});
});

describe("launch_workstream provisioning and id", () => {
	it("provisions the worktree from the derived slug and stages under a readable id with no agent handle", async () => {
		const previousUser = process.env.USER;
		process.env.USER = "btimothyhar";
		try {
			const harness = makeDeps();
			const { details } = await runLaunch(
				baseParams({
					workstream: { label: "Ignored Label", brief: "Brief.", worktreeSlug: " Feature*& Launch!! " },
				}),
				harness.deps,
			);

			assert.equal(details.status, "launched");
			assert.equal(details.id, "ignored-label");
			assert.equal(harness.provisionCalls.length, 1);
			assert.equal(harness.provisionCalls[0]?.label, "wt-bt/8e95-feature-launch");
			assert.equal(harness.provisionCalls[0]?.repoRoot, "/repo");
			assert.equal(details.worktree?.label, "wt-bt/8e95-feature-launch");
			// No agent is dispatched; the handle is stamped later by /workstream.
			assert.equal(details.agentHandle, undefined);
			assert.equal(harness.store.records[0]?.agent.handle, undefined);
			assert.match(details.next_step, /run `pi`.*\/workstream ignored-label/s);
		} finally {
			if (previousUser === undefined) delete process.env.USER;
			else process.env.USER = previousUser;
		}
	});

	it("returns a structured error when no repo workspace is available", async () => {
		const harness = makeDeps();
		harness.setWorkspace(makeWorkspace({ repo: null }));

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /current git repository/);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("reuses a non-failed matching launch without provisioning", async () => {
		const harness = makeDeps();
		harness.store.records.push({
			id: "launch-workstream-too",
			fingerprint: "different-fingerprint",
			repo: "org/repo",
			source: { dossierPath: "/graph/pages/Dossier.md" },
			workstream: { label: "Other", brief: "Existing." },
			worktree: { label: "wt-bt/8e95-launch-workstream-too", path: "/worktrees/existing", branch: "bt/existing" },
			agent: { handle: "swift-otter-9z9z9z", type: "worker" },
			setup: { status: "succeeded" },
			herdr: { status: "succeeded" },
			launch: { status: "succeeded" },
			createdAt: "2026-07-03T00:00:00.000Z",
			updatedAt: "2026-07-03T00:00:00.000Z",
		});

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "existing_launch");
		assert.equal(details.id, "launch-workstream-too");
		assert.equal(details.agentHandle, "swift-otter-9z9z9z");
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("fails when the target worktree already exists without a launch record", async () => {
		const harness = makeDeps();
		harness.setListedWorktrees([
			{
				kind: "git-worktree",
				label: "wt-bt/8e95-launch-workstream-too",
				path: "/worktrees/existing",
				branch: "bt/existing",
				created: false,
			},
		]);

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /different workstream\.worktreeSlug/);
		assert.equal(harness.store.records.length, 0);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("marks the record failed when worktree provisioning throws", async () => {
		const harness = makeDeps();
		harness.setProvision(async () => {
			throw new Error("cannot create branch");
		});

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.equal(harness.store.records.length, 1);
		assert.equal(harness.store.records[0]?.launch.status, "failed");
		assert.equal(harness.store.records[0]?.setup.status, "skipped");
		assert.match(harness.store.records[0]?.launch.error ?? "", /cannot create branch/);
	});
});

describe("launch_workstream setup behavior", () => {
	it("runs setup for a newly created worktree and continues on success", async () => {
		const harness = makeDeps();
		harness.setSetupCommand("make setup");

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.setupCalls.length, 1);
		assert.deepEqual(harness.setupCalls[0], {
			command: "make setup",
			worktreeDir: "/worktrees/org/repo/wt-bt/8e95-launch-workstream-too",
			repoRoot: "/repo",
		});
		assert.equal(harness.store.records[0]?.setup.status, "succeeded");
	});

	it("skips setup when the worktree already existed", async () => {
		const harness = makeDeps();
		harness.setSetupCommand("make setup");
		harness.setCreated(false);

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.setupCalls.length, 0);
		assert.equal(harness.store.records[0]?.setup.status, "skipped");
	});

	it("marks non-zero setup failed but still stages, without leaking stderr", async () => {
		const harness = makeDeps();
		harness.setSetupCommand("make setup");
		harness.setSetupResult({ ran: true, exitCode: 2, timedOut: false, stderrTail: "secret-stderr-boom" });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.store.records[0]?.setup.status, "failed");
		assert.match(harness.store.records[0]?.setup.message ?? "", /exited 2/);
		assert.doesNotMatch(JSON.stringify(details), /secret-stderr-boom/);
		assert.doesNotMatch(JSON.stringify(harness.store.records[0]), /secret-stderr-boom/);
	});

	it("marks timed-out setup failed but still stages", async () => {
		const harness = makeDeps();
		harness.setSetupCommand("make setup");
		harness.setSetupResult({ ran: true, exitCode: 143, timedOut: true, stderrTail: "timeout" });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.store.records[0]?.setup.status, "failed");
		assert.match(harness.store.records[0]?.setup.message ?? "", /timed out/);
	});
});

describe("launch_workstream Herdr and staging behavior", () => {
	it("opens a Herdr pane on the worktree and stages successfully", async () => {
		const harness = makeDeps();
		harness.setHerdrResult({ status: "opened", message: "opened", args: ["worktree", "open"] });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.store.records[0]?.herdr.status, "succeeded");
		assert.equal(harness.store.records[0]?.launch.status, "succeeded");
		assert.equal(harness.herdrCalls.length, 1);
		assert.deepEqual(harness.herdrCalls[0]?.worktree, {
			path: "/worktrees/org/repo/wt-bt/8e95-launch-workstream-too",
			label: "wt-bt/8e95-launch-workstream-too",
		});
		assert.match(details.next_step, /Herdr opened a pane/);
	});

	it("records Herdr failure without failing the staging, and does not leak stderr", async () => {
		const harness = makeDeps();
		harness.setHerdrResult({
			status: "failed",
			message: "Herdr failed.",
			error: "socket closed",
			stderr: "secret-herdr-stderr",
		});

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.store.records[0]?.launch.status, "succeeded");
		assert.equal(harness.store.records[0]?.herdr.status, "failed");
		assert.match(details.next_step, /Herdr pane failed to open/);
		assert.doesNotMatch(JSON.stringify(details), /secret-herdr-stderr/);
		assert.doesNotMatch(JSON.stringify(harness.store.records[0]), /secret-herdr-stderr/);
	});

	it("records Herdr skipped without failing the staging", async () => {
		const harness = makeDeps();
		harness.setHerdrResult({ status: "skipped", reason: "headless", message: "no UI" });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(harness.store.records[0]?.launch.status, "succeeded");
		assert.equal(harness.store.records[0]?.herdr.status, "skipped");
		assert.match(details.next_step, /no Herdr pane was opened/);
	});

	it("persists the record before side effects and reuses it on retry after a failure", async () => {
		const harness = makeDeps();
		let provisionCount = 0;
		harness.setProvision(async () => {
			provisionCount += 1;
			assert.equal(harness.store.records.length, 1, "record should be persisted before provisioning");
			throw new Error("provision crashed");
		});

		const first = await runLaunch(baseParams(), harness.deps);
		assert.equal(first.result.isError, true);
		assert.equal(harness.store.records[0]?.launch.status, "failed");
		const failedId = harness.store.records[0]?.id;

		// A retry supersedes the failed tombstone in place (same id), and re-provisions.
		const second = await runLaunch(baseParams(), harness.deps);
		assert.equal(second.result.isError, true);
		assert.equal(provisionCount, 2);
		assert.equal(harness.store.records.length, 1);
		assert.equal(harness.store.records[0]?.id, failedId);
	});

	it("succeeds when a retry supersedes a failed tombstone and provisioning recovers", async () => {
		const harness = makeDeps();
		let attempt = 0;
		harness.setProvision(async (_pi, _repoRoot, _repoName, label, branchName) => {
			attempt += 1;
			if (attempt === 1) throw new Error("transient failure");
			return { worktreeDir: `/worktrees/org/repo/${label}`, label, branch: branchName ?? label, created: true };
		});

		const first = await runLaunch(baseParams(), harness.deps);
		assert.equal(first.result.isError, true);

		const second = await runLaunch(baseParams(), harness.deps);
		assert.equal(second.details.status, "launched");
		assert.equal(harness.store.records.length, 1);
		assert.equal(harness.store.records[0]?.launch.status, "succeeded");
	});

	it("refreshes launch identity when retrying a failed tombstone", async () => {
		const harness = makeDeps();
		let attempt = 0;
		harness.setProvision(async (_pi, _repoRoot, _repoName, label, branchName) => {
			attempt += 1;
			if (attempt === 1) throw new Error("transient failure");
			return { worktreeDir: `/worktrees/org/repo/${label}`, label, branch: branchName ?? label, created: true };
		});

		const first = await runLaunch(baseParams(), harness.deps);
		assert.equal(first.result.isError, true);
		const staleFingerprint = harness.store.records[0]?.fingerprint;

		const second = await runLaunch(
			baseParams({
				source: { dossierPath: "/graph/pages/Updated.md" },
				workstream: {
					label: "Launch Workstream Too",
					brief: "Updated retry brief.",
					constraints: "Updated retry constraints.",
				},
			}),
			harness.deps,
		);

		assert.equal(second.details.status, "launched");
		assert.equal(harness.store.records.length, 1);
		assert.notEqual(harness.store.records[0]?.fingerprint, staleFingerprint);
		assert.deepEqual(harness.store.records[0]?.source, { dossierPath: "/graph/pages/Updated.md" });
		assert.deepEqual(harness.store.records[0]?.workstream, {
			label: "Launch Workstream Too",
			brief: "Updated retry brief.",
			constraints: "Updated retry constraints.",
		});
	});

	it("returns existing_launch when a concurrent attempt wins the append race with a live record", async () => {
		const harness = makeDeps();
		const live: WorkstreamLaunchRecord = {
			id: "launch-workstream-too",
			fingerprint: "fp",
			repo: "org/repo",
			source: { dossierPath: "/graph/pages/Dossier.md" },
			workstream: { label: "Launch Workstream Too", brief: "b" },
			worktree: { label: "wt-bt/8e95-launch-workstream-too", path: "/w", branch: "bt/x" },
			agent: { handle: "swift-otter-abc123", type: "worker" },
			setup: { status: "succeeded" },
			herdr: { status: "succeeded" },
			launch: { status: "succeeded" },
			createdAt: "2026-07-03T00:00:00.000Z",
			updatedAt: "2026-07-03T00:00:00.000Z",
		};
		harness.store.records.push(live);
		// Simulate the race: findDuplicate sees nothing, but the guarded append finds the live record.
		harness.store.duplicateOverride = null;

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "existing_launch");
		assert.equal(details.agentHandle, "swift-otter-abc123");
		assert.equal(harness.provisionCalls.length, 0);
	});
});
