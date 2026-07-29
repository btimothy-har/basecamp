import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { CatalogItem } from "#core/catalog/index.ts";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import {
	buildCapabilitiesIndex,
	buildUnsafeEditGuidance,
	buildWorktreeWarning,
} from "#system-prompt/context-builders.ts";

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

		assert.match(index, /Apply a skill whose instructions are already in context/);
		assert.match(index, /load it with `skill` when they are not/);
		assert.doesNotMatch(index, /Use `skill` to load .* before using it/);
		assert.doesNotMatch(index, /skill\(\{ name:/);
	});

	it("flattens a multi-line tool description onto one index line", () => {
		// Tool descriptions are authored as multi-line prose but the index is a one-line-per-item
		// list, so a leaked newline would corrupt every line after it.
		const toolItems: CatalogItem[] = [
			{
				type: "tools",
				name: "bash",
				description: "\n  Run a shell command.\n\n\tSupports:\n    - pipes\n    - redirects\n  ",
			},
			{ type: "tools", name: "ls", description: "List a directory." },
		];

		const index = buildCapabilitiesIndex({ toolItems, skillItems: [], agentItems: [], includeAgents: false });

		const lines = index.split("\n");
		const heading = lines.indexOf("Tools (2):");
		assert.notEqual(heading, -1);
		// every whitespace run — newlines, tabs, indentation — collapses to a single space,
		// and leading/trailing whitespace is dropped
		assert.deepEqual(lines.slice(heading + 1, heading + 3), [
			"- bash — Run a shell command. Supports: - pipes - redirects",
			"- ls — List a directory.",
		]);
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
