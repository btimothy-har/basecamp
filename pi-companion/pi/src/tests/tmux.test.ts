import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	buildCompanionCommand,
	buildKillArgs,
	buildRespawnArgs,
	buildSplitArgs,
	parsePaneId,
	shouldCreatePane,
} from "../tmux.ts";

describe("panes/tmux", () => {
	describe("shouldCreatePane", () => {
		it("returns true for interactive primary sessions inside tmux", () => {
			assert.equal(
				shouldCreatePane({
					tmux: "/tmp/tmux.sock,123,0",
					tmuxPane: "%1",
					hasUI: true,
					agentDepth: 0,
				}),
				true,
			);
		});

		it("returns false when tmux env is missing", () => {
			assert.equal(
				shouldCreatePane({
					tmuxPane: "%1",
					hasUI: true,
					agentDepth: 0,
				}),
				false,
			);
		});

		it("returns false when tmux pane env is missing", () => {
			assert.equal(
				shouldCreatePane({
					tmux: "/tmp/tmux.sock,123,0",
					hasUI: true,
					agentDepth: 0,
				}),
				false,
			);
		});

		it("returns false when ui is unavailable", () => {
			assert.equal(
				shouldCreatePane({
					tmux: "/tmp/tmux.sock,123,0",
					tmuxPane: "%1",
					hasUI: false,
					agentDepth: 0,
				}),
				false,
			);
		});

		it("returns false for subagents", () => {
			assert.equal(
				shouldCreatePane({
					tmux: "/tmp/tmux.sock,123,0",
					tmuxPane: "%1",
					hasUI: true,
					agentDepth: 1,
				}),
				false,
			);
		});
	});

	describe("buildCompanionCommand", () => {
		it("quotes snapshot path and cwd", () => {
			assert.equal(
				buildCompanionCommand("/tmp/with space/snapshot.json", "/tmp/worktree cwd"),
				"basecamp companion dashboard --snapshot '/tmp/with space/snapshot.json' --cwd '/tmp/worktree cwd'",
			);
		});

		it("escapes single quotes", () => {
			assert.equal(
				buildCompanionCommand("/tmp/it's-snapshot.json", "/tmp/it's-cwd"),
				"basecamp companion dashboard --snapshot '/tmp/it'\\''s-snapshot.json' --cwd '/tmp/it'\\''s-cwd'",
			);
		});

		it("appends quoted scratch dir when provided", () => {
			assert.equal(
				buildCompanionCommand("/tmp/snap.json", "/tmp/cwd", "/tmp/pi/basecamp"),
				"basecamp companion dashboard --snapshot '/tmp/snap.json' --cwd '/tmp/cwd' --scratch '/tmp/pi/basecamp'",
			);
		});
	});

	describe("buildSplitArgs", () => {
		it("builds split-window argv sizing the companion pane to 65%", () => {
			assert.deepEqual(buildSplitArgs("%2", "/tmp/worktree", "echo hi"), [
				"split-window",
				"-d",
				"-h",
				"-l",
				"65%",
				"-t",
				"%2",
				"-c",
				"/tmp/worktree",
				"-P",
				"-F",
				"#{pane_id}",
				"echo hi",
			]);
		});
	});

	describe("buildRespawnArgs", () => {
		it("builds respawn-pane argv", () => {
			assert.deepEqual(buildRespawnArgs("%3", "/tmp/new-worktree", "echo hi"), [
				"respawn-pane",
				"-k",
				"-t",
				"%3",
				"-c",
				"/tmp/new-worktree",
				"echo hi",
			]);
		});
	});

	describe("buildKillArgs", () => {
		it("builds kill-pane argv", () => {
			assert.deepEqual(buildKillArgs("%3"), ["kill-pane", "-t", "%3"]);
		});
	});

	describe("parsePaneId", () => {
		it("returns pane id from plain output", () => {
			assert.equal(parsePaneId("%5\n"), "%5");
		});

		it("returns pane id when surrounded by blank lines", () => {
			assert.equal(parsePaneId("\n\n%8\n\n"), "%8");
		});

		it("returns null for empty output", () => {
			assert.equal(parsePaneId(""), null);
		});

		it("returns null for non-matching output", () => {
			assert.equal(parsePaneId("created pane"), null);
		});
	});
});
