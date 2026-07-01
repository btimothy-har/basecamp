import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	computeWorkstreamPlanId,
	emptyWorkstreamLaunchState,
	findPersistedWorkstreamEntryByWorktreeLabel,
	loadWorkstreamLaunchState,
	saveWorkstreamLaunchState,
	workstreamStateFilePath,
} from "../planning/workstream-state.ts";

function tempDir(): string {
	return fs.mkdtempSync(path.join(os.tmpdir(), "pi-workstream-state-"));
}

describe("workstream launch state", () => {
	it("uses the dedicated workstreams path convention", () => {
		const home = path.join(tempDir(), "home");

		assert.equal(
			workstreamStateFilePath("session-123", path.join(home, ".pi", "basecamp", "workstreams")),
			path.join(home, ".pi", "basecamp", "workstreams", "session-123.json"),
		);
	});

	it("loads an empty state when the file is missing or invalid", () => {
		const dir = tempDir();
		const file = path.join(dir, "state.json");

		assert.deepEqual(loadWorkstreamLaunchState(file), emptyWorkstreamLaunchState());

		fs.writeFileSync(file, "not json");
		assert.deepEqual(loadWorkstreamLaunchState(file), emptyWorkstreamLaunchState());

		fs.writeFileSync(file, JSON.stringify({ version: 999, runs: {} }));
		assert.deepEqual(loadWorkstreamLaunchState(file), emptyWorkstreamLaunchState());
	});

	it("saves and loads versioned run receipts", () => {
		const file = path.join(tempDir(), "nested", "state.json");
		const state = emptyWorkstreamLaunchState();
		state.runs.plan123 = {
			planId: "plan123",
			plan: {
				goal: "Goal",
				context: "Context",
				design: "Design",
				success: "Success",
				boundaries: "Boundaries",
			},
			status: "approved",
			handoff_status: "workstreams_dispatched",
			workstreams: {
				core: {
					id: "core",
					label: "Core",
					dependsOn: [],
					status: "dispatched",
					agent: { handle: "worker-1", type: "worker" },
					worktree: { label: "wt-core", path: "/worktrees/wt-core", branch: "bt/core", created: true },
				},
			},
		};

		saveWorkstreamLaunchState(file, state);

		assert.deepEqual(loadWorkstreamLaunchState(file), state);
		assert.equal(fs.existsSync(`${file}.tmp`), false);
	});

	it("computes stable deterministic plan ids from approved plan content", () => {
		const input = {
			goal: "Goal",
			context: "Context",
			design: "Design",
			success: "Success",
			boundaries: "Boundaries",
			workstreams: [
				{
					id: "core",
					label: "Core",
					scope: "Scope",
					outcome: "Outcome",
					boundaries: "Boundaries",
					dependsOn: [],
				},
			],
		};

		assert.equal(computeWorkstreamPlanId(input), computeWorkstreamPlanId(input));
		assert.notEqual(computeWorkstreamPlanId(input), computeWorkstreamPlanId({ ...input, success: "Different" }));
	});

	it("finds the newest persisted workstream entry by worktree label", () => {
		const state = emptyWorkstreamLaunchState();
		state.runs.old = {
			planId: "old",
			plan: { goal: "Goal", context: "Context", design: "Design", success: "Success", boundaries: "Boundaries" },
			updatedAt: "2026-01-01T00:00:00.000Z",
			workstreams: {
				core: {
					id: "core",
					label: "Core",
					dependsOn: [],
					status: "dispatched",
					agent: { handle: "worker-old", type: "worker" },
					worktree: { label: "wt-core", path: "/old", branch: "bt/core", created: true },
					updatedAt: "2026-01-01T00:00:00.000Z",
				},
			},
		};
		state.runs.new = {
			planId: "new",
			plan: { goal: "Goal", context: "Context", design: "Design", success: "Success", boundaries: "Boundaries" },
			updatedAt: "2026-01-02T00:00:00.000Z",
			workstreams: {
				core: {
					id: "core",
					label: "Core",
					dependsOn: [],
					status: "dispatched",
					agent: { handle: "worker-new", type: "worker" },
					worktree: { label: "wt-core", path: "/new", branch: "bt/core", created: false },
					updatedAt: "2026-01-02T00:00:00.000Z",
				},
			},
		};

		assert.equal(findPersistedWorkstreamEntryByWorktreeLabel(state, "wt-core")?.agent?.handle, "worker-new");
		assert.equal(findPersistedWorkstreamEntryByWorktreeLabel(state, "missing"), null);
	});

	it("treats dependency order as equivalent in deterministic plan ids", () => {
		const input = {
			goal: "Goal",
			context: "Context",
			design: "Design",
			success: "Success",
			boundaries: "Boundaries",
			workstreams: [
				{
					id: "ui",
					label: "UI",
					scope: "Scope",
					outcome: "Outcome",
					boundaries: "Boundaries",
					dependsOn: ["core", "schema"],
				},
			],
		};

		assert.equal(
			computeWorkstreamPlanId(input),
			computeWorkstreamPlanId({
				...input,
				workstreams: [{ ...input.workstreams[0]!, dependsOn: ["schema", "core"] }],
			}),
		);
	});
});
