import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "../constants.ts";
import {
	createAgentWorktree,
	deleteBranch,
	lockWorktree,
	removeWorktree,
	unlockWorktree,
} from "../worktrees/lifecycle.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

function argsEqual(actual: string[], expected: string[]): boolean {
	return actual.length === expected.length && actual.every((arg, i) => arg === expected[i]);
}

function execPi(handler: (args: string[]) => ExecResult, calls: string[][] = []): ExtensionAPI {
	return {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			assert.equal(command, "git");
			calls.push(args);
			return handler(args);
		},
	} as ExtensionAPI;
}

describe("createAgentWorktree", () => {
	it("branches from baseRef onto the agent-<id>/<name> branch and locks the worktree", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-agent-${process.pid}-${Date.now()}`;
		const label = "agent-3f9a2c/worker";
		const baseRef = "abc123";
		const worktreeDir = path.join(WORKTREES_ROOT, repoName, "agent-3f9a2c", "worker");
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		const addArgs = ["-C", repoRoot, "worktree", "add", "-b", label, worktreeDir, baseRef];
		const lockArgs = ["-C", repoRoot, "worktree", "lock", "--reason", "basecamp agent run", worktreeDir];
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: `worktree ${repoRoot}\nbranch refs/heads/main\n\n`, stderr: "" };
			}
			if (argsEqual(args, addArgs) || argsEqual(args, lockArgs)) return { code: 0, stdout: "", stderr: "" };
			throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
		}, calls);

		const result = await createAgentWorktree(pi, repoRoot, repoName, label, baseRef);

		assert.deepEqual(result, { worktreeDir, label, branch: label, created: true });
		assert.ok(
			calls.some((a) => argsEqual(a, addArgs)),
			"branches from baseRef",
		);
		assert.ok(
			calls.some((a) => argsEqual(a, lockArgs)),
			"locks after create",
		);
	});

	it("rejects a malformed label before touching git", async () => {
		const pi = execPi(() => {
			throw new Error("git should not run for an invalid label");
		});
		await assert.rejects(() => createAgentWorktree(pi, "/repo", "repo", "bad label", "HEAD"), /Invalid worktree label/);
	});

	it("removes the worktree and branch if the lock fails, then rethrows", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-lf-${process.pid}-${Date.now()}`;
		const label = "agent-deadbe/worker";
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: `worktree ${repoRoot}\n\n`, stderr: "" };
			}
			if (args.includes("lock")) {
				return { code: 1, stdout: "", stderr: "fatal: some lock error" };
			}
			return { code: 0, stdout: "", stderr: "" };
		}, calls);

		await assert.rejects(() => createAgentWorktree(pi, repoRoot, repoName, label, "HEAD"), /some lock error/);
		assert.ok(
			calls.some((a) => a.includes("remove")),
			"removes the worktree after a lock failure",
		);
		assert.ok(
			calls.some((a) => a.includes("-D")),
			"deletes the branch after a lock failure",
		);
	});
});

describe("worktree lock/unlock/remove", () => {
	it("lock is idempotent when git reports already-locked", async () => {
		const pi = execPi(() => ({ code: 1, stdout: "", stderr: "fatal: 'wt' is already locked" }));
		await assert.doesNotReject(() => lockWorktree(pi, "/repo", "/wt"));
	});

	it("unlock is idempotent when git reports not-locked", async () => {
		const pi = execPi(() => ({ code: 1, stdout: "", stderr: "fatal: 'wt' is not locked" }));
		await assert.doesNotReject(() => unlockWorktree(pi, "/repo", "/wt"));
	});

	it("lock throws on a genuine failure", async () => {
		const pi = execPi(() => ({ code: 1, stdout: "", stderr: "fatal: some other error" }));
		await assert.rejects(() => lockWorktree(pi, "/repo", "/wt"), /Failed to lock worktree/);
	});

	it("removeWorktree unlocks first, then removes with --force", async () => {
		const calls: string[][] = [];
		const pi = execPi(() => ({ code: 0, stdout: "", stderr: "" }), calls);
		await removeWorktree(pi, "/repo", "/wt", { force: true });

		const unlockIdx = calls.findIndex((a) => a.includes("unlock"));
		const removeIdx = calls.findIndex((a) => a.includes("remove"));
		assert.notEqual(unlockIdx, -1, "unlocks");
		assert.notEqual(removeIdx, -1, "removes");
		assert.ok(unlockIdx < removeIdx, "unlock precedes remove");
		assert.ok(calls[removeIdx]?.includes("--force"), "force remove");
	});

	it("deleteBranch is idempotent when the branch is missing", async () => {
		const pi = execPi(() => ({ code: 1, stdout: "", stderr: "error: branch 'x' not found." }));
		await assert.doesNotReject(() => deleteBranch(pi, "/repo", "x"));
	});

	it("deleteBranch throws on a genuine failure", async () => {
		const pi = execPi(() => ({ code: 1, stdout: "", stderr: "fatal: something else" }));
		await assert.rejects(() => deleteBranch(pi, "/repo", "x"), /Failed to delete branch/);
	});
});
