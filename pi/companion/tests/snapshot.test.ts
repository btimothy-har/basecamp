import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import {
	buildSnapshot,
	companionLiveSnapshotPath,
	companionSnapshotPath,
	removeSnapshotFile,
	writeSnapshotFile,
} from "../snapshot/model.ts";

describe("companion/snapshot", () => {
	describe("buildSnapshot", () => {
		it("excludes deleted tasks and computes progress over non-deleted tasks", () => {
			const snapshot = buildSnapshot({
				sessionId: "session-1",
				title: "Companion writer",
				goal: "Ship companion writer",
				rawTasks: [
					{ label: "A", status: "completed", notes: "done" },
					{ label: "B", status: "active", notes: null },
					{ label: "C", status: "deleted", notes: "skip" },
					{ label: "D", status: "pending", notes: "todo" },
				],
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
				{ label: "A", status: "completed", notes: "done" },
				{ label: "B", status: "active", notes: null },
				{ label: "D", status: "pending", notes: "todo" },
			]);
			assert.deepEqual(snapshot.progress, { completed: 1, total: 3 });
			assert.equal(snapshot.title, "Companion writer");
			assert.equal(snapshot.updatedAt, "2025-01-02T03:04:05.000Z");
		});

		it("handles null goal, empty tasks, and null worktree", () => {
			const snapshot = buildSnapshot({
				sessionId: "session-2",
				title: null,
				goal: null,
				rawTasks: [],
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
			assert.equal(snapshot.worktree, null);
		});
	});

	describe("companionSnapshotPath", () => {
		it("sanitizes session id and joins with provided directory", () => {
			const result = companionSnapshotPath("abc/def:ghi", "/tmp/companion");
			assert.equal(result, "/tmp/companion/abc_def_ghi.json");
		});
	});

	describe("companionLiveSnapshotPath", () => {
		it("uses a sanitized process identifier in the companion snapshot directory", () => {
			const result = companionLiveSnapshotPath("/tmp/companion", "pid/123:worker");
			assert.equal(result, "/tmp/companion/.live-pid_123_worker.json");
		});

		it("defaults to the current process id", () => {
			const result = companionLiveSnapshotPath("/tmp/companion");
			assert.equal(result, `/tmp/companion/.live-${process.pid}.json`);
		});
	});

	describe("snapshot file IO", () => {
		it("writes and removes per-session and live snapshot files", () => {
			const dir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-companion-snapshot-"));
			const snapshot = buildSnapshot({
				sessionId: "session-1",
				title: null,
				goal: "Keep snapshots current",
				rawTasks: [{ label: "A", status: "active", notes: null }],
				agentMode: "executor",
				worktree: null,
				repoName: "basecamp",
				model: "model-1",
				skillsUsed: [],
				effectiveCwd: "/tmp/repo",
				now: new Date("2025-03-04T05:06:07.000Z"),
			});
			const perSessionPath = companionSnapshotPath(snapshot.sessionId, dir);
			const livePath = companionLiveSnapshotPath(dir, "pid-1");

			writeSnapshotFile(perSessionPath, snapshot);
			writeSnapshotFile(livePath, snapshot);

			assert.deepEqual(JSON.parse(fs.readFileSync(perSessionPath, "utf8")), snapshot);
			assert.deepEqual(JSON.parse(fs.readFileSync(livePath, "utf8")), snapshot);

			removeSnapshotFile(perSessionPath);
			removeSnapshotFile(livePath);

			assert.equal(fs.existsSync(perSessionPath), false);
			assert.equal(fs.existsSync(livePath), false);

			fs.rmSync(dir, { recursive: true, force: true });
		});
	});
});
