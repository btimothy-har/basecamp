import assert from "node:assert/strict";
import * as fs from "node:fs";
import { describe, it } from "node:test";
import type { AgentWorkspaceProvision } from "../agent-workspace.ts";
import { buildAgentLaunchSpec, type SharedAgentLaunchInput } from "../launch.ts";
import { createMockPi, installDaemonToolTestHooks } from "./harness.ts";

const REPO_ROOT = "/repo/main-checkout";

function provision(overrides: Partial<AgentWorkspaceProvision> = {}): AgentWorkspaceProvision {
	return {
		kind: "deliverable",
		worktreeDir: "/worktrees/repo/agent-abc123/scout",
		label: "agent-abc123/scout",
		branch: "agent/quiet-badger-3dc450",
		baseOid: "baseoid",
		branchCreated: true,
		repoRoot: REPO_ROOT,
		...overrides,
	};
}

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
		agentWorkspace: null,
		...overrides,
	};
}

function toolsFromArgs(args: string[]): string[] {
	const idx = args.indexOf("--tools");
	return idx === -1 ? [] : (args[idx + 1]?.split(",") ?? []);
}

describe("buildAgentLaunchSpec workspace resolution", () => {
	installDaemonToolTestHooks();

	it("spawns every repo-backed agent inside its own workspace with write/edit and no flags", () => {
		const p = provision();
		const result = buildAgentLaunchSpec(
			launchInput(
				{ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: { path: "/worktrees/repo/abc" } },
				"own",
				{ agentWorkspace: p },
			),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			assert.equal(result.plan.spawnCwd, p.worktreeDir, "cwd is the agent's own workspace (auto-adopted)");
			assert.equal(result.plan.args.includes("--worktree-dir"), false);
			assert.equal(result.plan.args.includes("--read-only"), false);
			const tools = toolsFromArgs(result.plan.args);
			assert.equal(tools.includes("write"), true);
			assert.equal(tools.includes("edit"), true);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});

	it("stamps the child env with the agent's own workspace, not the parent's", () => {
		const p = provision();
		const result = buildAgentLaunchSpec(
			launchInput(
				{ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: { path: "/worktrees/repo/abc" } },
				"env",
				{ agentWorkspace: p },
			),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			assert.equal(result.plan.environment.BASECAMP_WORKTREE_DIR, p.worktreeDir);
			assert.equal(result.plan.environment.BASECAMP_WORKTREE_LABEL, p.label);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});

	it("fails closed when a repo-backed dispatch has no provisioned workspace", () => {
		const result = buildAgentLaunchSpec(
			launchInput({ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: null }, "failclosed"),
		);

		assert.equal(result.ok, false);
		if (result.ok) return;
		assert.match(result.message, /requires a provisioned workspace/);
	});

	it("launches a non-repo session's agent at the launch cwd with no workspace", () => {
		const result = buildAgentLaunchSpec(launchInput({ launchCwd: "/scratch/dir", repo: null }, "norepo"));

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			assert.equal(result.plan.spawnCwd, "/scratch/dir");
			assert.equal(result.plan.args.includes("--worktree-dir"), false);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});

	it("puts the ask contract in the task text for a detached persona-less workspace", () => {
		const p = provision({ kind: "ask", branch: null, branchCreated: false, label: "agent-abc123/ask" });
		const result = buildAgentLaunchSpec(
			launchInput({ protectedRoot: REPO_ROOT, repo: { root: REPO_ROOT }, activeWorktree: null }, "ask", {
				agentWorkspace: p,
			}),
		);

		assert.equal(result.ok, true);
		if (!result.ok) return;
		try {
			// Persona-less runs keep the default prompt assembly; the contract rides in the task.
			assert.equal(result.plan.args.includes("--agent-prompt"), false);
			assert.match(result.plan.args.at(-1) ?? "", /detached snapshot workspace/);
		} finally {
			fs.rmSync(result.plan.agentDir, { recursive: true, force: true });
		}
	});
});
