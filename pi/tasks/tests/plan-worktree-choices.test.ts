import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";
import {
	buildExecutionWorktreeChoices,
	CUSTOM_WORKTREE_CHOICE,
	customWorktreeTarget,
	type ExecutionWorktreeTarget,
	suggestWorktreeTarget,
	userWorktreePrefix,
} from "../workflows/handoff/worktree-choices.ts";

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

function target(slug: string): ExecutionWorktreeTarget {
	return { worktreeLabel: `wt/${slug}`, branchName: `bt/${slug}` };
}

describe("suggestWorktreeTarget", () => {
	it("builds a generic wt/<slug> worktree with a user-prefixed branch", () => {
		assert.deepEqual(suggestWorktreeTarget("Fallback Goal", "worktree-prefix", "a1b2", "btimothyhar"), {
			worktreeLabel: "wt/worktree-prefix",
			branchName: "bt/a1b2-worktree-prefix",
		});
		assert.equal(userWorktreePrefix("B Timothy"), "bt");
	});

	it("only the branch carries the user prefix; the worktree label is prefix-free", () => {
		assert.deepEqual(suggestWorktreeTarget("Fallback Goal", "worktree-prefix", "a1b2", "!!!"), {
			worktreeLabel: "wt/worktree-prefix",
			branchName: "un/a1b2-worktree-prefix",
		});
		assert.equal(userWorktreePrefix("b"), "un");
		assert.equal(userWorktreePrefix(null), "un");
	});

	it("normalizes the goal when no worktree slug is provided", () => {
		assert.deepEqual(suggestWorktreeTarget("Add user worktree prefix", null, "a1b2", "btimothyhar"), {
			worktreeLabel: "wt/add-user-worktree-prefix",
			branchName: "bt/a1b2-add-user-worktree-prefix",
		});
	});

	it("caps the branch (the durable identifier) at 32 characters", () => {
		const suggested = suggestWorktreeTarget("Goal", "abcdefghijklmnopqrstuvwxyz0123456789", "a1b2", "btimothyhar");

		assert.equal(suggested.worktreeLabel, "wt/abcdefghijklmnopqrstuvwx");
		assert.equal(suggested.branchName, "bt/a1b2-abcdefghijklmnopqrstuvwx");
		assert.equal(suggested.branchName.length, 32);
	});

	it("normalizes custom labels without double-prefixing", () => {
		const expected = { worktreeLabel: "wt/custom-label", branchName: "bt/a1b2-custom-label" };

		assert.deepEqual(customWorktreeTarget("custom label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("wt/custom-label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("wt-bt/a1b2-custom-label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("bt/a1b2-custom-label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("a1b2-custom-label", "a1b2", "btimothyhar"), expected);
	});

	it("omits the tag segment when the session tag is empty", () => {
		assert.deepEqual(suggestWorktreeTarget("Goal", "slug", "", "btimothyhar"), {
			worktreeLabel: "wt/slug",
			branchName: "bt/slug",
		});
	});
});

describe("buildExecutionWorktreeChoices", () => {
	it("preserves suggested-first behavior when there is no active worktree", () => {
		const suggested = target("suggested");
		const existing = [worktree("other"), worktree("detached", { branch: null })];

		const result = buildExecutionWorktreeChoices(suggested, existing, null);

		assert.deepEqual(result.choices, [
			"Create: wt/suggested",
			"Resume: other (wt/other)",
			"Resume: detached (detached)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Create: wt/suggested"), suggested);
		assert.deepEqual(result.targetsByChoice.get("Resume: detached (detached)"), {
			worktreeLabel: "detached",
			branchName: null,
		});
	});

	it("places the registered active worktree first and resolves to its label", () => {
		const suggested = target("suggested");
		const active = worktree("current", { path: "/tmp/worktrees/current" });
		const existing = [worktree("other"), worktree("current", { path: "/tmp/worktrees/current/" })];

		const result = buildExecutionWorktreeChoices(suggested, existing, active);

		assert.equal(result.choices[0], "Current: current (wt/current)");
		assert.deepEqual(result.targetsByChoice.get("Current: current (wt/current)"), {
			worktreeLabel: "current",
			branchName: null,
		});
		assert.deepEqual(result.choices, [
			"Current: current (wt/current)",
			"Create: wt/suggested",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Create: wt/suggested"), suggested);
		assert.deepEqual(result.targetsByChoice.get("Resume: other (wt/other)"), {
			worktreeLabel: "other",
			branchName: null,
		});
	});

	it("does not match the active worktree by label alone", () => {
		const active = worktree("current", { path: "/tmp/other/current" });
		const existing = [worktree("current", { path: "/tmp/worktrees/current" }), worktree("other")];

		const result = buildExecutionWorktreeChoices(target("suggested"), existing, active);

		assert.deepEqual(result.choices, [
			"Create: wt/suggested",
			"Resume: current (wt/current)",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
	});

	it("suppresses the suggested entry when the active worktree is the suggestion", () => {
		const suggested = target("suggested");
		const active = worktree(suggested.worktreeLabel, { branch: suggested.branchName });
		const existing = [worktree(suggested.worktreeLabel, { branch: suggested.branchName }), worktree("other")];

		const result = buildExecutionWorktreeChoices(suggested, existing, active);

		assert.deepEqual(result.choices, [
			"Current: wt/suggested (bt/suggested)",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Current: wt/suggested (bt/suggested)"), {
			worktreeLabel: "wt/suggested",
			branchName: null,
		});
	});

	it("resumes an existing suggested-label worktree by reusing its branch, not creating fresh", () => {
		const suggested = target("suggested");
		const active = worktree("current");
		const existing = [
			worktree("current"),
			worktree(suggested.worktreeLabel, { branch: suggested.branchName }),
			worktree("other"),
		];

		const result = buildExecutionWorktreeChoices(suggested, existing, active);

		assert.deepEqual(result.choices, [
			"Current: current (wt/current)",
			"Resume: wt/suggested (bt/suggested)",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(Array.from(result.targetsByChoice.entries()), [
			["Current: current (wt/current)", { worktreeLabel: "current", branchName: null }],
			["Resume: wt/suggested (bt/suggested)", { worktreeLabel: "wt/suggested", branchName: null }],
			["Resume: other (wt/other)", { worktreeLabel: "other", branchName: null }],
		]);
	});

	it("formats an existing suggested worktree as resumable by reusing its branch", () => {
		const suggested = target("suggested");
		const existing = [worktree(suggested.worktreeLabel, { branch: suggested.branchName })];

		const result = buildExecutionWorktreeChoices(suggested, existing, null);

		assert.deepEqual(result.choices, ["Resume: wt/suggested (bt/suggested)", CUSTOM_WORKTREE_CHOICE]);
		assert.deepEqual(result.targetsByChoice.get("Resume: wt/suggested (bt/suggested)"), {
			worktreeLabel: "wt/suggested",
			branchName: null,
		});
	});

	it("formats a detached active worktree as current and detached", () => {
		const active = worktree("current", { branch: null });
		const existing = [worktree("current", { branch: null })];

		const result = buildExecutionWorktreeChoices(target("suggested"), existing, active);

		assert.deepEqual(result.choices, ["Current: current (detached)", "Create: wt/suggested", CUSTOM_WORKTREE_CHOICE]);
	});

	it("omits an unregistered active worktree from the selector", () => {
		const active = worktree("current");
		const existing = [worktree("other")];

		const result = buildExecutionWorktreeChoices(target("suggested"), existing, active);

		assert.deepEqual(result.choices, ["Create: wt/suggested", "Resume: other (wt/other)", CUSTOM_WORKTREE_CHOICE]);
	});

	it("leaves the custom choice unmapped", () => {
		const result = buildExecutionWorktreeChoices(target("suggested"), [], null);

		assert.deepEqual(result.choices, ["Create: wt/suggested", CUSTOM_WORKTREE_CHOICE]);
		assert.equal(result.targetsByChoice.get(CUSTOM_WORKTREE_CHOICE), undefined);
	});
});
