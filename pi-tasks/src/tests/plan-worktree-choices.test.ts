import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "pi-core/platform/workspace.ts";
import {
	buildExecutionWorktreeChoices,
	suggestWorktreeLabel,
	userWorktreePrefix,
} from "../planning/worktree-choices.ts";

function worktree(label: string, overrides: Partial<WorkspaceWorktree> = {}): WorkspaceWorktree {
	return {
		kind: "git-worktree",
		label,
		path: `/tmp/worktrees/${label}`,
		branch: `wt/${label}`,
		created: false,
		...overrides,
	};
}

describe("suggestWorktreeLabel", () => {
	it("uses the first two safe characters from the user id", () => {
		assert.equal(suggestWorktreeLabel("Fallback Goal", "worktree-prefix", "btimothyhar"), "bt-worktree-prefix");
		assert.equal(userWorktreePrefix("B Timothy"), "bt");
	});

	it("falls back when the user id has no safe prefix", () => {
		assert.equal(suggestWorktreeLabel("Fallback Goal", "worktree-prefix", "!!!"), "un-worktree-prefix");
		assert.equal(userWorktreePrefix(null), "un");
	});

	it("normalizes the goal when no worktree slug is provided", () => {
		assert.equal(suggestWorktreeLabel("Add user worktree prefix", null, "btimothyhar"), "bt-add-user-worktree-prefix");
	});

	it("caps suggested labels at 32 characters", () => {
		const label = suggestWorktreeLabel("Goal", "abcdefghijklmnopqrstuvwxyz0123456789", "btimothyhar");

		assert.equal(label, "bt-abcdefghijklmnopqrstuvwxyz012");
		assert.equal(label.length, 32);
	});
});

describe("buildExecutionWorktreeChoices", () => {
	it("preserves suggested-first behavior when there is no active worktree", () => {
		const existing = [worktree("other"), worktree("detached", { branch: null })];

		const result = buildExecutionWorktreeChoices("suggested", existing, null);

		assert.deepEqual(result.choices, ["Create: suggested", "Resume: other (wt/other)", "Resume: detached (detached)"]);
		assert.equal(result.labelsByChoice.get("Create: suggested"), "suggested");
		assert.equal(result.labelsByChoice.get("Resume: detached (detached)"), "detached");
	});

	it("places the registered active worktree first and resolves to its label", () => {
		const active = worktree("current", { path: "/tmp/worktrees/current" });
		const existing = [worktree("other"), worktree("current", { path: "/tmp/worktrees/current/" })];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.equal(result.choices[0], "Current: current (wt/current)");
		assert.equal(result.labelsByChoice.get("Current: current (wt/current)"), "current");
		assert.deepEqual(result.choices, [
			"Current: current (wt/current)",
			"Create: suggested",
			"Resume: other (wt/other)",
		]);
		assert.equal(result.labelsByChoice.get("Create: suggested"), "suggested");
		assert.equal(result.labelsByChoice.get("Resume: other (wt/other)"), "other");
	});

	it("does not match the active worktree by label alone", () => {
		const active = worktree("current", { path: "/tmp/other/current" });
		const existing = [worktree("current", { path: "/tmp/worktrees/current" }), worktree("other")];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.deepEqual(result.choices, ["Create: suggested", "Resume: current (wt/current)", "Resume: other (wt/other)"]);
	});

	it("suppresses the suggested entry when the active worktree is the suggestion", () => {
		const active = worktree("suggested");
		const existing = [worktree("suggested"), worktree("other")];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.deepEqual(result.choices, ["Current: suggested (wt/suggested)", "Resume: other (wt/other)"]);
		assert.equal(result.labelsByChoice.get("Current: suggested (wt/suggested)"), "suggested");
	});

	it("does not duplicate active or suggested worktrees in remaining worktrees", () => {
		const active = worktree("current");
		const existing = [worktree("current"), worktree("suggested"), worktree("other")];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.deepEqual(result.choices, [
			"Current: current (wt/current)",
			"Resume: suggested (wt/suggested)",
			"Resume: other (wt/other)",
		]);
		assert.deepEqual(Array.from(result.labelsByChoice.entries()), [
			["Current: current (wt/current)", "current"],
			["Resume: suggested (wt/suggested)", "suggested"],
			["Resume: other (wt/other)", "other"],
		]);
	});

	it("formats an existing suggested worktree as resumable with its branch", () => {
		const existing = [worktree("suggested")];

		const result = buildExecutionWorktreeChoices("suggested", existing, null);

		assert.deepEqual(result.choices, ["Resume: suggested (wt/suggested)"]);
		assert.equal(result.labelsByChoice.get("Resume: suggested (wt/suggested)"), "suggested");
	});

	it("formats a detached active worktree as current and detached", () => {
		const active = worktree("current", { branch: null });
		const existing = [worktree("current", { branch: null })];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.deepEqual(result.choices, ["Current: current (detached)", "Create: suggested"]);
	});

	it("omits an unregistered active worktree from the selector", () => {
		const active = worktree("current");
		const existing = [worktree("other")];

		const result = buildExecutionWorktreeChoices("suggested", existing, active);

		assert.deepEqual(result.choices, ["Create: suggested", "Resume: other (wt/other)"]);
	});

	it("does not include a custom label choice", () => {
		const result = buildExecutionWorktreeChoices("suggested", [], null);

		assert.deepEqual(result.choices, ["Create: suggested"]);
		assert.deepEqual(Array.from(result.labelsByChoice.entries()), [["Create: suggested", "suggested"]]);
	});
});
