import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import type { WorkstreamLaunchRecord } from "../workstreams/launch-state.ts";
import {
	executeListWorkstreamLaunches,
	type ListWorkstreamLaunchesDeps,
	type ListWorkstreamLaunchesResultDetails,
} from "../workstreams/tools.ts";

class FakeListStore {
	readonly records: WorkstreamLaunchRecord[] = [];
	path = "/tmp/workstream-launch-index.json";

	launchStatePath(): string {
		return this.path;
	}

	listRecords(_filePath: string, filter: { repo?: string; dossierPath?: string }): WorkstreamLaunchRecord[] {
		return clone(this.records).filter((record) => {
			if (filter.repo && record.repo !== filter.repo) return false;
			if (filter.dossierPath && record.source.dossierPath !== filter.dossierPath) return false;
			return true;
		});
	}
}

class EmptyListStore {
	launchStatePath(): string {
		return "/tmp/malformed-workstream-launch-index.json";
	}

	listRecords(): WorkstreamLaunchRecord[] {
		return [];
	}
}

function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
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

function makeRecord(overrides: Partial<WorkstreamLaunchRecord> = {}): WorkstreamLaunchRecord {
	const base: WorkstreamLaunchRecord = {
		id: "launch-1",
		fingerprint: "fingerprint-1",
		repo: "org/repo",
		source: { dossierPath: "/graph/pages/Dossier.md", repoPagePath: "/graph/pages/Repo.md" },
		workstream: { label: "Launch Workstream Too", brief: "Implement the launch workstream tool." },
		worktree: {
			label: "wt-bt/8e95-launch-workstream-too",
			path: "/worktrees/org/repo/wt-bt/8e95-launch-workstream-too",
			branch: "bt/8e95-launch-workstream-too",
			created: true,
		},
		agent: { handle: "worker-1", type: "worker" },
		setup: { status: "succeeded", message: "setup ok", error: "setup stderr secret" },
		herdr: { status: "succeeded", message: "herdr ok", error: "herdr stderr secret" },
		launch: { status: "succeeded", message: "launch ok", error: "launch stderr secret" },
		createdAt: "2026-07-03T00:00:00.000Z",
		updatedAt: "2026-07-03T00:00:00.000Z",
	};

	return {
		...base,
		...overrides,
		source: { ...base.source, ...overrides.source },
		workstream: { ...base.workstream, ...overrides.workstream },
		worktree: { ...base.worktree, ...overrides.worktree },
		agent: { ...base.agent, ...overrides.agent },
		setup: overrides.setup ?? base.setup,
		herdr: overrides.herdr ?? base.herdr,
		launch: overrides.launch ?? base.launch,
	};
}

function makeDeps(overrides: Partial<ListWorkstreamLaunchesDeps> = {}) {
	const store = new FakeListStore();
	let workspace: WorkspaceState | null = makeWorkspace();
	const deps: ListWorkstreamLaunchesDeps = {
		getWorkspaceState: () => workspace,
		store,
		...overrides,
	};

	return {
		deps,
		store,
		setWorkspace(value: WorkspaceState | null) {
			workspace = value;
		},
	};
}

function runList(params: unknown, deps: ListWorkstreamLaunchesDeps) {
	const result = executeListWorkstreamLaunches(params, makeContext(), deps);
	return { result, details: result.details as ListWorkstreamLaunchesResultDetails };
}

describe("list_workstream_launches", () => {
	it("lists all launches for the current repo sorted newest-first", () => {
		const harness = makeDeps();
		harness.store.records.push(
			makeRecord({ id: "older", createdAt: "2026-07-01T00:00:00.000Z" }),
			makeRecord({ id: "newer", createdAt: "2026-07-03T00:00:00.000Z" }),
			makeRecord({ id: "other-repo", repo: "org/other", createdAt: "2026-07-04T00:00:00.000Z" }),
		);

		const { result, details } = runList({}, harness.deps);

		assert.equal(result.isError, undefined);
		assert.equal(details.status, "ok");
		assert.equal(details.count, 2);
		assert.deepEqual(
			details.launches.map((launch) => launch.id),
			["newer", "older"],
		);
		assert.match(details.next_step, /agentHandle/);
		assert.match(details.next_step, /do not treat/i);
	});

	it("filters by dossierPath", () => {
		const harness = makeDeps();
		harness.store.records.push(
			makeRecord({ id: "wanted", source: { dossierPath: "/graph/pages/Wanted.md" } }),
			makeRecord({ id: "other", source: { dossierPath: "/graph/pages/Other.md" } }),
		);

		const { details } = runList({ dossierPath: " /graph/pages/Wanted.md " }, harness.deps);

		assert.equal(details.count, 1);
		assert.equal(details.launches[0]?.id, "wanted");
		assert.equal(details.launches[0]?.dossierPath, "/graph/pages/Wanted.md");
	});

	it("filters by label substring case-insensitively", () => {
		const harness = makeDeps();
		harness.store.records.push(
			makeRecord({ id: "alpha", workstream: { label: "Alpha Launch", brief: "Alpha brief." } }),
			makeRecord({ id: "beta", workstream: { label: "Beta Worker", brief: "Beta brief." } }),
		);

		const { details } = runList({ label: "launch" }, harness.deps);

		assert.equal(details.count, 1);
		assert.equal(details.launches[0]?.id, "alpha");
	});

	it("toggles full brief vs truncated preview with includeBrief", () => {
		const harness = makeDeps();
		const longBrief = `${"Long brief sentence. ".repeat(20)}Final secret tail.`;
		harness.store.records.push(makeRecord({ id: "long", workstream: { label: "Long", brief: longBrief } }));

		const preview = runList({}, harness.deps).details.launches[0];
		assert.ok(preview);
		assert.equal(preview.brief, undefined);
		assert.ok(preview.briefPreview);
		assert.ok(preview.briefPreview.length <= 200);
		assert.ok(preview.briefPreview.endsWith("…"));
		assert.notEqual(preview.briefPreview, longBrief);

		const full = runList({ includeBrief: true }, harness.deps).details.launches[0];
		assert.ok(full);
		assert.equal(full.brief, longBrief);
		assert.equal(full.briefPreview, undefined);
	});

	it("returns no_workspace with isError when no repo workspace is available", () => {
		const harness = makeDeps();
		harness.setWorkspace(makeWorkspace({ repo: null }));

		const { result, details } = runList({}, harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "no_workspace");
		assert.equal(details.count, 0);
		assert.deepEqual(details.launches, []);
	});

	it("returns an empty list gracefully when the store has no usable records", () => {
		const harness = makeDeps({ store: new EmptyListStore() });

		const { result, details } = runList({}, harness.deps);

		assert.equal(result.isError, undefined);
		assert.equal(details.status, "ok");
		assert.equal(details.count, 0);
		assert.deepEqual(details.launches, []);
	});

	it("exposes agent handles and status enums but not stored error strings", () => {
		const harness = makeDeps();
		harness.store.records.push(
			makeRecord({
				id: "safe",
				workstream: { label: "Safe", brief: "Safe brief.", constraints: "Stay read-only." },
				setup: { status: "failed", message: "setup message", error: "setup stderr secret" },
				herdr: { status: "skipped", message: "herdr message", error: "herdr stderr secret" },
				launch: { status: "succeeded", message: "launch message", error: "launch stderr secret" },
			}),
		);

		const { details } = runList({}, harness.deps);
		const entry = details.launches[0];
		assert.ok(entry);
		assert.equal(entry.agentHandle, "worker-1");
		assert.equal(entry.agentType, "worker");
		assert.equal(entry.setupStatus, "failed");
		assert.equal(entry.herdrStatus, "skipped");
		assert.equal(entry.launchStatus, "succeeded");
		assert.equal(entry.constraints, "Stay read-only.");

		const serialized = JSON.stringify(details);
		assert.doesNotMatch(serialized, /stderr secret/);
		assert.doesNotMatch(serialized, /setup message/);
		assert.doesNotMatch(serialized, /herdr message/);
		assert.doesNotMatch(serialized, /launch message/);
	});
});
