import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "#core/platform/workspace.ts";
import {
	buildExecutionWorktreeChoices,
	CUSTOM_WORKTREE_CHOICE,
	customWorktreeTarget,
	type ExecutionWorktreeTarget,
	suggestWorktreeTarget,
	userWorktreePrefix,
} from "../planning/handoff/worktree-choices.ts";

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
	return { worktreeLabel: `wt-bt/${slug}`, branchName: `bt/${slug}` };
}

describe("suggestWorktreeTarget", () => {
	it("uses the first two safe characters from the user id", () => {
		assert.deepEqual(suggestWorktreeTarget("Fallback Goal", "worktree-prefix", "a1b2", "btimothyhar"), {
			worktreeLabel: "wt-bt/a1b2-worktree-prefix",
			branchName: "bt/a1b2-worktree-prefix",
		});
		assert.equal(userWorktreePrefix("B Timothy"), "bt");
	});

	it("falls back when the user id does not have two safe prefix characters", () => {
		assert.deepEqual(suggestWorktreeTarget("Fallback Goal", "worktree-prefix", "a1b2", "!!!"), {
			worktreeLabel: "wt-un/a1b2-worktree-prefix",
			branchName: "un/a1b2-worktree-prefix",
		});
		assert.equal(userWorktreePrefix("b"), "un");
		assert.equal(userWorktreePrefix(null), "un");
	});

	it("normalizes the goal when no worktree slug is provided", () => {
		assert.deepEqual(suggestWorktreeTarget("Add user worktree prefix", null, "a1b2", "btimothyhar"), {
			worktreeLabel: "wt-bt/a1b2-add-user-worktree-pre",
			branchName: "bt/a1b2-add-user-worktree-pre",
		});
	});

	it("caps suggested worktree labels at 32 characters", () => {
		const suggested = suggestWorktreeTarget("Goal", "abcdefghijklmnopqrstuvwxyz0123456789", "a1b2", "btimothyhar");

		assert.equal(suggested.worktreeLabel, "wt-bt/a1b2-abcdefghijklmnopqrstu");
		assert.equal(suggested.branchName, "bt/a1b2-abcdefghijklmnopqrstu");
		assert.equal(suggested.worktreeLabel.length, 32);
	});

	it("normalizes custom labels without double-prefixing", () => {
		const expected = { worktreeLabel: "wt-bt/a1b2-custom-label", branchName: "bt/a1b2-custom-label" };

		assert.deepEqual(customWorktreeTarget("custom label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("wt-bt/a1b2-custom-label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("bt/a1b2-custom-label", "a1b2", "btimothyhar"), expected);
		assert.deepEqual(customWorktreeTarget("a1b2-custom-label", "a1b2", "btimothyhar"), expected);
	});

	it("omits the tag segment when the session tag is empty", () => {
		assert.deepEqual(suggestWorktreeTarget("Goal", "slug", "", "btimothyhar"), {
			worktreeLabel: "wt-bt/slug",
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
			"Create: wt-bt/suggested",
			"Resume: other (wt/other)",
			"Resume: detached (detached)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Create: wt-bt/suggested"), suggested);
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
			"Create: wt-bt/suggested",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Create: wt-bt/suggested"), suggested);
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
			"Create: wt-bt/suggested",
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
			"Current: wt-bt/suggested (bt/suggested)",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(result.targetsByChoice.get("Current: wt-bt/suggested (bt/suggested)"), {
			worktreeLabel: "wt-bt/suggested",
			branchName: null,
		});
	});

	it("does not duplicate active or suggested worktrees in remaining worktrees", () => {
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
			"Resume: wt-bt/suggested (bt/suggested)",
			"Resume: other (wt/other)",
			CUSTOM_WORKTREE_CHOICE,
		]);
		assert.deepEqual(Array.from(result.targetsByChoice.entries()), [
			["Current: current (wt/current)", { worktreeLabel: "current", branchName: null }],
			["Resume: wt-bt/suggested (bt/suggested)", suggested],
			["Resume: other (wt/other)", { worktreeLabel: "other", branchName: null }],
		]);
	});

	it("formats an existing suggested worktree as resumable with its branch", () => {
		const suggested = target("suggested");
		const existing = [worktree(suggested.worktreeLabel, { branch: suggested.branchName })];

		const result = buildExecutionWorktreeChoices(suggested, existing, null);

		assert.deepEqual(result.choices, ["Resume: wt-bt/suggested (bt/suggested)", CUSTOM_WORKTREE_CHOICE]);
		assert.deepEqual(result.targetsByChoice.get("Resume: wt-bt/suggested (bt/suggested)"), suggested);
	});

	it("formats a detached active worktree as current and detached", () => {
		const active = worktree("current", { branch: null });
		const existing = [worktree("current", { branch: null })];

		const result = buildExecutionWorktreeChoices(target("suggested"), existing, active);

		assert.deepEqual(result.choices, [
			"Current: current (detached)",
			"Create: wt-bt/suggested",
			CUSTOM_WORKTREE_CHOICE,
		]);
	});

	it("omits an unregistered active worktree from the selector", () => {
		const active = worktree("current");
		const existing = [worktree("other")];

		const result = buildExecutionWorktreeChoices(target("suggested"), existing, active);

		assert.deepEqual(result.choices, ["Create: wt-bt/suggested", "Resume: other (wt/other)", CUSTOM_WORKTREE_CHOICE]);
	});

	it("leaves the custom choice unmapped", () => {
		const result = buildExecutionWorktreeChoices(target("suggested"), [], null);

		assert.deepEqual(result.choices, ["Create: wt-bt/suggested", CUSTOM_WORKTREE_CHOICE]);
		assert.equal(result.targetsByChoice.get(CUSTOM_WORKTREE_CHOICE), undefined);
	});
});
