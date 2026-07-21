import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import { buildCapabilitiesIndex, buildUnsafeEditGuidance, buildWorktreeWarning } from "../context-builders.ts";

function workspace(overrides: Partial<WorkspaceState>): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: "/repo",
		scratchDir: "/tmp/pi/repo",
		repo: {
			isRepo: true,
			name: "repo",
			root: "/repo",
			remoteUrl: null,
		},
		protectedRoot: "/repo",
		activeWorktree: {
			kind: "git-worktree",
			label: "default",
			path: "/worktree/default",
			branch: "main",
			created: false,
		},
		unsafeEdit: false,
		...overrides,
	};
}

describe("capabilities index", () => {
	it("distinguishes loading a skill from applying it", () => {
		const index = buildCapabilitiesIndex({
			toolItems: [],
			skillItems: [],
			agentItems: [],
			includeAgents: false,
		});

		assert.match(index, /Skill lifecycle:/);
		assert.match(index, /Before applying a relevant skill, load it if its instructions are not already present\./);
		assert.match(index, /Reuse loaded instructions across ordinary turns and tasks/);
		assert.match(
			index,
			/Reload only when the instructions are no longer in active context or an intentional refresh is needed\./,
		);
		assert.doesNotMatch(index, /Use `skill` to load .* before using it/);
	});
});

describe("unsafe-edit context", () => {
	it("keeps the default active-worktree warning when unsafe-edit is off", () => {
		const warning = buildWorktreeWarning(workspace({ unsafeEdit: false }));
		assert.equal(
			warning,
			"⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory. Do not edit the protected repository checkout.",
		);
	});

	it("includes unsafe-edit guidance for active worktrees when enabled", () => {
		const warning = buildWorktreeWarning(
			workspace({
				unsafeEdit: true,
				activeWorktree: {
					kind: "git-worktree",
					label: "feature",
					path: "/worktree/feature",
					branch: "wt/feature",
					created: true,
				},
			}),
		);
		assert.ok(warning?.includes("⚠ UNSAFE-EDIT MODE ACTIVE:"));
		assert.ok(warning?.includes("File `edit`/`write` calls may modify the protected checkout directly."));
		assert.doesNotMatch(warning ?? "", /Do not edit the protected repository checkout/);
	});

	it("states active worktree requirements and subagent restrictions when unsafe-edit is on", () => {
		const guidance = buildUnsafeEditGuidance(
			workspace({
				unsafeEdit: true,
				activeWorktree: {
					kind: "git-worktree",
					label: "feature",
					path: "/worktree/feature",
					branch: "wt/feature",
					created: true,
				},
			}),
		);
		assert.ok(guidance?.includes("Commits and mutating git commands"));
		assert.ok(guidance?.includes("must run from the active execution worktree."));
		assert.ok(guidance?.includes("Subagents do not inherit unsafe-edit authority."));
	});
});
