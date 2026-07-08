import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { copilotWorktreeTarget, userWorktreePrefix } from "../worktree-target.ts";

describe("userWorktreePrefix", () => {
	it("uses the first two safe characters from the user id", () => {
		assert.equal(userWorktreePrefix("B Timothy"), "bt");
	});

	it("falls back when the user id does not have two safe prefix characters", () => {
		assert.equal(userWorktreePrefix("b"), "un");
		assert.equal(userWorktreePrefix(null), "un");
	});
});

describe("copilotWorktreeTarget", () => {
	it("builds a copilot worktree label and user-prefixed branch", () => {
		assert.deepEqual(copilotWorktreeTarget("Add worktree helpers", "swift-mountain-river", "btimothyhar"), {
			worktreeLabel: "copilot/swift-mountain-river",
			branchName: "bt/add-worktree-helpers",
		});
	});

	it("falls back to the default prefix when the user id lacks two safe characters", () => {
		assert.deepEqual(copilotWorktreeTarget("Refactor module", "calm-quiet-forest", "!!!"), {
			worktreeLabel: "copilot/calm-quiet-forest",
			branchName: "un/refactor-module",
		});
	});

	it("normalizes the work name into a slug", () => {
		assert.deepEqual(copilotWorktreeTarget("Fix: Bug #42!", "brave-meadow-lake", "btimothyhar"), {
			worktreeLabel: "copilot/brave-meadow-lake",
			branchName: "bt/fix-bug-42",
		});
	});

	it("caps the branch slug to the suggested worktree label length minus the prefix", () => {
		const target = copilotWorktreeTarget("abcdefghijklmnopqrstuvwxyz0123456789", "fast-stream-valley", "btimothyhar");

		assert.equal(target.worktreeLabel, "copilot/fast-stream-valley");
		assert.equal(target.branchName, "bt/abcdefghijklmnopqrstuvwxyz012");
	});
});
