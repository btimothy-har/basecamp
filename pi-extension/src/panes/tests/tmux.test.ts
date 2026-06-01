import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildKillArgs, buildSplitArgs, parsePaneId, shouldCreatePane } from "../tmux.ts";

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

	describe("buildSplitArgs", () => {
		it("builds split-window argv", () => {
			assert.deepEqual(buildSplitArgs("%2", "echo hi"), [
				"split-window",
				"-d",
				"-h",
				"-t",
				"%2",
				"-P",
				"-F",
				"#{pane_id}",
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
