import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "pi-core/platform/workspace.ts";
import { shouldReuseActiveWorktreeForHandoff, workspaceWorktreeToHandoffWorktree } from "../planning/plan.ts";

function worktree(overrides: Partial<WorkspaceWorktree> = {}): WorkspaceWorktree {
	return {
		kind: "git-worktree",
		label: "wt-bt/current-workstream",
		path: "/tmp/worktrees/wt-bt/current-workstream",
		branch: "bt/current-workstream",
		created: false,
		...overrides,
	};
}

describe("shouldReuseActiveWorktreeForHandoff", () => {
	it("reuses active worktrees only for workstream agents", () => {
		const activeWorktree = worktree();

		assert.equal(shouldReuseActiveWorktreeForHandoff("workstream_agent", activeWorktree), true);
		assert.equal(shouldReuseActiveWorktreeForHandoff("workstream_agent", null), false);
		assert.equal(shouldReuseActiveWorktreeForHandoff(null, activeWorktree), false);
		assert.equal(shouldReuseActiveWorktreeForHandoff("copilot", activeWorktree), false);
	});
});

describe("workspaceWorktreeToHandoffWorktree", () => {
	it("maps workspace worktrees to handoff worktrees", () => {
		assert.deepEqual(workspaceWorktreeToHandoffWorktree(worktree({ created: true })), {
			worktreeDir: "/tmp/worktrees/wt-bt/current-workstream",
			label: "wt-bt/current-workstream",
			branch: "bt/current-workstream",
			created: true,
		});
	});

	it("uses detached when the workspace worktree has no branch", () => {
		assert.deepEqual(workspaceWorktreeToHandoffWorktree(worktree({ branch: null })), {
			worktreeDir: "/tmp/worktrees/wt-bt/current-workstream",
			label: "wt-bt/current-workstream",
			branch: "detached",
			created: false,
		});
	});
});
