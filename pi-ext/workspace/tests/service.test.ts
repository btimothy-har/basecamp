import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { WORKTREES_ROOT } from "../src/constants.ts";
import { WorkspaceRuntimeService } from "../src/service.ts";

const REPO_ROOT = "/repo";
const REPO_NAME = "repo";
const LABEL = "feature";
const BRANCH = "wt/feature";
const REMOTE_URL = "git@github.com:test/repo.git";
const WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_NAME, LABEL);

interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

type ExecResult = { code: number; stdout: string; stderr: string };

function restoreBasecampEnv(snapshot: Record<string, string | undefined>): void {
	for (const key of Object.keys(process.env)) {
		if (key.startsWith("BASECAMP_") && !(key in snapshot)) delete process.env[key];
	}
	for (const [key, value] of Object.entries(snapshot)) {
		if (value === undefined) delete process.env[key];
		else process.env[key] = value;
	}
}

function snapshotBasecampEnv(): Record<string, string | undefined> {
	return Object.fromEntries(
		Object.entries(process.env)
			.filter(([key]) => key.startsWith("BASECAMP_"))
			.map(([key, value]) => [key, value]),
	);
}

function gitWorktreeListOutput(): string {
	return [
		`worktree ${REPO_ROOT}`,
		"branch refs/heads/main",
		"",
		`worktree ${WORKTREE_DIR}`,
		`branch refs/heads/${BRANCH}`,
		"",
	].join("\n");
}

function createPi(): { pi: ExtensionAPI; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			calls.push({ command, args, options });
			assert.equal(command, "git");

			if (args.join(" ") === "rev-parse --show-toplevel") {
				return { code: 0, stdout: `${REPO_ROOT}\n`, stderr: "" };
			}
			if (args.join(" ") === `-C ${REPO_ROOT} remote get-url origin`) {
				return { code: 0, stdout: `${REMOTE_URL}\n`, stderr: "" };
			}
			if (args.join(" ") === `-C ${REPO_ROOT} symbolic-ref --quiet --short refs/remotes/origin/HEAD`) {
				return { code: 0, stdout: "origin/main\n", stderr: "" };
			}
			if (args.join(" ") === `-C ${REPO_ROOT} branch --show-current`) {
				return { code: 0, stdout: "main\n", stderr: "" };
			}
			if (args.join(" ") === `-C ${REPO_ROOT} status --porcelain`) {
				return { code: 0, stdout: "", stderr: "" };
			}
			if (args.join(" ") === `-C ${REPO_ROOT} worktree list --porcelain`) {
				return { code: 0, stdout: gitWorktreeListOutput(), stderr: "" };
			}

			throw new Error(`Unexpected git call: ${args.join(" ")}`);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

async function initializeAndActivate(
	launchCwd: string,
): Promise<{ service: WorkspaceRuntimeService; calls: ExecCall[] }> {
	const { pi, calls } = createPi();
	const service = new WorkspaceRuntimeService(pi);
	await service.initialize({
		launchCwd,
		unsafeEditFlag: false,
		unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false },
	});
	await service.activateExecutionTarget(LABEL);
	return { service, calls };
}

describe("WorkspaceRuntimeService effective cwd", () => {
	it("preserves protected repo subdirectory when activating an existing worktree", async (t) => {
		const envSnapshot = snapshotBasecampEnv();
		t.after(() => restoreBasecampEnv(envSnapshot));

		const launchCwd = path.join(REPO_ROOT, "packages", "app");
		const { service, calls } = await initializeAndActivate(launchCwd);

		assert.equal(service.getEffectiveCwd(), path.join(WORKTREE_DIR, "packages", "app"));
		assert.equal(service.current()?.executionTarget?.created, false);
		assert.ok(calls.some((call) => call.args.join(" ") === `-C ${REPO_ROOT} worktree list --porcelain`));
	});

	it("uses worktree root when launch cwd is outside protected root", async (t) => {
		const envSnapshot = snapshotBasecampEnv();
		t.after(() => restoreBasecampEnv(envSnapshot));

		const { service } = await initializeAndActivate("/outside");

		assert.equal(service.current()?.protectedRoot, REPO_ROOT);
		assert.equal(service.current()?.launchCwd, path.resolve("/outside"));
		assert.equal(service.getEffectiveCwd(), WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_DIR, WORKTREE_DIR);
		assert.equal(process.env.BASECAMP_WORKTREE_LABEL, LABEL);
	});
});
