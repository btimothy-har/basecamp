import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildSnapshot, companionSnapshotPath } from "../snapshot.ts";

describe("companion/snapshot", () => {
	describe("buildSnapshot", () => {
		it("excludes deleted tasks and computes progress over non-deleted tasks", () => {
			const snapshot = buildSnapshot({
				sessionId: "session-1",
				title: "Companion writer",
				goal: "Ship companion writer",
				rawTasks: [
					{ label: "A", description: "d", criteria: "c", status: "completed", notes: "done" },
					{ label: "B", description: "d", criteria: "c", status: "active", notes: null },
					{ label: "C", description: "d", criteria: "c", status: "deleted", notes: "skip" },
					{ label: "D", description: "d", criteria: "c", status: "pending", notes: "todo" },
				],
				cycles: [],
				agentMode: "executor",
				worktree: { label: "wt-a", branch: "main", path: "/tmp/wt-a" },
				repoName: "basecamp",
				model: "claude-sonnet",
				skillsUsed: ["planning", "sql"],
				effectiveCwd: "/tmp/wt-a",
				now: new Date("2025-01-02T03:04:05.000Z"),
			});

			assert.equal(snapshot.tasks.length, 3);
			assert.deepEqual(snapshot.tasks, [
				{ label: "A", description: "d", criteria: "c", status: "completed", notes: "done" },
				{ label: "B", description: "d", criteria: "c", status: "active", notes: null },
				{ label: "D", description: "d", criteria: "c", status: "pending", notes: "todo" },
			]);
			assert.deepEqual(snapshot.progress, { completed: 1, total: 3 });
			assert.deepEqual(snapshot.goals, []);
			assert.equal(snapshot.title, "Companion writer");
			assert.equal(snapshot.updatedAt, "2025-01-02T03:04:05.000Z");
		});

		it("handles null goal, empty tasks, and null worktree", () => {
			const snapshot = buildSnapshot({
				sessionId: "session-2",
				title: null,
				goal: null,
				rawTasks: [],
				cycles: [],
				agentMode: null,
				worktree: null,
				repoName: null,
				model: null,
				skillsUsed: [],
				effectiveCwd: "/tmp/repo",
				now: new Date("2025-02-03T04:05:06.000Z"),
			});

			assert.equal(snapshot.goal, null);
			assert.deepEqual(snapshot.tasks, []);
			assert.deepEqual(snapshot.progress, { completed: 0, total: 0 });
			assert.deepEqual(snapshot.goals, []);
			assert.equal(snapshot.worktree, null);
		});

		it("maps goal cycles into goals[] with full task fields, filtering deleted and computing progress", () => {
			const snapshot = buildSnapshot({
				sessionId: "session-3",
				title: null,
				goal: "Active goal",
				rawTasks: [],
				cycles: [
					{
						goal: "First goal",
						tasks: [
							{ label: "T1", description: "d1", criteria: "c1", notes: "n1", status: "completed", review: null },
							{ label: "T2", description: "d2", criteria: "c2", notes: null, status: "deleted", review: null },
						],
						planRef: null,
						agentMode: "executor",
						active: false,
						archivedAt: "2025-01-01T00:00:00.000Z",
					},
					{
						goal: "Active goal",
						tasks: [{ label: "T3", description: "d3", criteria: "c3", notes: "n3", status: "active", review: null }],
						planRef: null,
						agentMode: null,
						active: true,
						archivedAt: null,
					},
				],
				agentMode: null,
				worktree: null,
				repoName: null,
				model: null,
				skillsUsed: [],
				effectiveCwd: "/tmp/repo",
				now: new Date("2025-03-03T03:03:03.000Z"),
			});

			assert.equal(snapshot.goals.length, 2);
			assert.deepEqual(snapshot.goals[0], {
				goal: "First goal",
				tasks: [{ label: "T1", description: "d1", criteria: "c1", status: "completed", notes: "n1" }],
				agentMode: "executor",
				active: false,
				archivedAt: "2025-01-01T00:00:00.000Z",
				progress: { completed: 1, total: 1 },
			});
			const activeGoal = snapshot.goals[1];
			assert.ok(activeGoal);
			assert.equal(activeGoal.active, true);
			assert.equal(activeGoal.goal, "Active goal");
			assert.deepEqual(activeGoal.progress, { completed: 0, total: 1 });
			const activeTask = activeGoal.tasks[0];
			assert.ok(activeTask);
			assert.equal(activeTask.description, "d3");
		});
	});

	describe("companionSnapshotPath", () => {
		it("sanitizes session id and joins with provided directory", () => {
			const result = companionSnapshotPath("abc/def:ghi", "/tmp/companion");
			assert.equal(result, "/tmp/companion/abc_def_ghi.json");
		});
	});
});
