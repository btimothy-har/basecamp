import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { CatalogItem } from "../../platform/catalog.ts";
import type { WorkspaceState } from "../../platform/workspace.ts";
import { buildMemoryGuidance, buildUnsafeEditGuidance, buildWorktreeWarning } from "../context.ts";

function tool(name: string): CatalogItem {
	return { type: "tools", name, description: "" };
}

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

describe("buildMemoryGuidance", () => {
	it("returns null when no memory tools are present", () => {
		assert.equal(buildMemoryGuidance([tool("read"), tool("bash")]), null);
	});

	it("emits the instruction block when memory tools are present", () => {
		const block = buildMemoryGuidance([tool("memory_search"), tool("session_search"), tool("memory_remember")]);
		assert.ok(block);
		assert.match(block, /^# Memory/);
		assert.match(block, /memory_search/);
		assert.match(block, /session_search/);
		assert.match(block, /memory_remember/);
	});

	it("emits when only one of the memory tools is present", () => {
		assert.ok(buildMemoryGuidance([tool("session_search")]));
		assert.ok(buildMemoryGuidance([tool("memory_search")]));
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
		assert.ok(warning?.includes("Parent file `edit`/`write` calls may modify the protected checkout directly."));
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
		assert.ok(guidance?.includes("Commits and mutating `safe_git` commands"));
		assert.ok(guidance?.includes("must run from the active execution worktree."));
		assert.ok(guidance?.includes("Subagents do not inherit unsafe-edit authority."));
	});
});
