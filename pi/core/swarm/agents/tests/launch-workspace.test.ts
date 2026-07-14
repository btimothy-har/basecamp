import assert from "node:assert/strict";
import * as fs from "node:fs";
import { describe, it } from "node:test";
import { buildAgentLaunchSpec, type SharedAgentLaunchInput } from "../launch.ts";
import type { AgentConfig } from "../types.ts";
import { createMockPi, installDaemonToolTestHooks } from "./harness.ts";

const REPO_ROOT = "/repo/main-checkout";

const MUTATIVE_WORKER: AgentConfig = {
	name: "worker",
	description: "implement in your own worktree",
	model: "default",
	systemPrompt: "do the work",
	source: "builtin",
	filePath: "/builtin/worker.md",
	readOnly: false,
};

function launchInput(
	workspace: SharedAgentLaunchInput["workspace"],
	nameSuffix: string,
	overrides: Partial<SharedAgentLaunchInput> = {},
): SharedAgentLaunchInput {
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
		...overrides,
	};
}

function toolsFromArgs(args: string[]): string[] {
	const idx = args.indexOf("--tools");
	return idx === -1 ? [] : (args[idx + 1]?.split(",") ?? []);
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

describe("buildAgentLaunchSpec mutative worktree", () => {
	installDaemonToolTestHooks();

	it("spawns a mutative agent directly in its own worktree with write/edit and no --read-only", () => {
		const wn = "/worktrees/repo/agent-00000000/worker";
		const result = buildAgentLaunchSpec(
			launchInput(
				{ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: { path: "/worktrees/repo/abc" } },
				"mut",
				{ requestedAgent: "worker", getAgents: () => [MUTATIVE_WORKER], mutativeWorktreeDir: wn },
			),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			// cwd IS the worktree (auto-adopted); no --worktree-dir, no --read-only.
			assert.equal(result.plan.spawnCwd, wn);
			assert.equal(result.plan.worktreeDir, null);
			assert.equal(result.plan.args.includes("--worktree-dir"), false);
			assert.equal(result.plan.args.includes("--read-only"), false);
			const tools = toolsFromArgs(result.plan.args);
			assert.equal(tools.includes("write"), true);
			assert.equal(tools.includes("edit"), true);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});

	it("fails closed when a mutative agent has no provisioned worktree", () => {
		const result = buildAgentLaunchSpec(
			launchInput(
				{ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: { path: "/worktrees/repo/abc" } },
				"mutfail",
				{ requestedAgent: "worker", getAgents: () => [MUTATIVE_WORKER] },
			),
		);

		assert.equal(result.ok, false);
		if (result.ok) return;
		assert.match(result.message, /requires a provisioned worktree/);
	});
});
