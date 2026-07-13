import assert from "node:assert/strict";
import * as fs from "node:fs";
import { describe, it } from "node:test";
import { buildAgentLaunchSpec, type SharedAgentLaunchInput } from "../launch.ts";
import { createMockPi, installDaemonToolTestHooks } from "./harness.ts";

const REPO_ROOT = "/repo/main-checkout";

function launchInput(workspace: SharedAgentLaunchInput["workspace"], nameSuffix: string): SharedAgentLaunchInput {
	const { pi } = createMockPi();
	return {
		pi,
		getAgents: () => [],
		basecampExtensionRoot: process.cwd(),
		namePrefix: "agent-254",
		nameSuffix,
		task: "inspect the workspace",
		modelContext: undefined,
		resolveModelAlias: (model) => model,
		workspace,
		agentId: `00000000-0000-4000-8000-25400000000${nameSuffix.length}`,
		parentSession: "parent-session",
		project: "proj",
	};
}

/**
 * Regression guard for #254: a worker dispatched with no active worktree must
 * land in the protected main checkout (its own workspace guard then blocks
 * structured writes there — see project/workspace/tests/guards.test.ts), and no
 * `--worktree-dir` is passed.
 */
describe("buildAgentLaunchSpec workspace resolution", () => {
	installDaemonToolTestHooks();

	it("spawns a no-worktree agent in the protected main checkout without --worktree-dir", () => {
		const result = buildAgentLaunchSpec(
			launchInput({ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: null }, "noworktree"),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			assert.equal(result.plan.spawnCwd, REPO_ROOT);
			assert.equal(result.plan.worktreeDir, null);
			assert.equal(result.plan.args.includes("--worktree-dir"), false);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});

	it("keeps the protected main checkout as cwd and redirects file work via --worktree-dir when a worktree is active", () => {
		const worktreePath = "/worktrees/repo/feature";
		const result = buildAgentLaunchSpec(
			launchInput(
				{ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: { path: worktreePath } },
				"worktree",
			),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			assert.equal(result.plan.spawnCwd, REPO_ROOT);
			assert.equal(result.plan.worktreeDir, worktreePath);
			const flagIndex = result.plan.args.indexOf("--worktree-dir");
			assert.notEqual(flagIndex, -1);
			assert.equal(result.plan.args[flagIndex + 1], worktreePath);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});
});
