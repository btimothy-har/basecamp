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
	it("atomically branches from baseRef and locks the worktree", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-agent-${process.pid}-${Date.now()}`;
		const label = "agent-3f9a2c/worker";
		const baseRef = "abc123";
		const worktreeDir = path.join(WORKTREES_ROOT, repoName, "agent-3f9a2c", "worker");
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		const addArgs = [
			"-C",
			repoRoot,
			"worktree",
			"add",
			"--lock",
			"--reason",
			"basecamp agent run",
			"-b",
			label,
			worktreeDir,
			baseRef,
		];
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: `worktree ${repoRoot}\nbranch refs/heads/main\n\n`, stderr: "" };
			}
			if (argsEqual(args, addArgs)) return { code: 0, stdout: "", stderr: "" };
			throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
		}, calls);

		const result = await createAgentWorktree(pi, repoRoot, repoName, label, baseRef);

		assert.deepEqual(result, { worktreeDir, label, branch: label, created: true });
		assert.equal(calls.filter((args) => argsEqual(args, addArgs)).length, 1);
		assert.equal(
			calls.some((args) => args.includes("lock") && !args.includes("--lock")),
			false,
		);
	});

	it("rejects a malformed label before touching git", async () => {
		const pi = execPi(() => {
			throw new Error("git should not run for an invalid label");
		});
		await assert.rejects(() => createAgentWorktree(pi, "/repo", "repo", "bad label", "HEAD"), /Invalid worktree label/);
	});

	it("does not clean unrelated state when git rolls back a failed add", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-clean-failure-${process.pid}-${Date.now()}`;
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (args.includes("list")) return { code: 0, stdout: `worktree ${repoRoot}\n\n`, stderr: "" };
			if (args.includes("add")) return { code: 1, stdout: "", stderr: "fatal: atomic add failed" };
			throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
		}, calls);

		await assert.rejects(
			() => createAgentWorktree(pi, repoRoot, repoName, "agent-cleanup/worker", "HEAD"),
			/atomic add failed/,
		);
		assert.equal(
			calls.some((args) => args.includes("remove") || args.includes("-D")),
			false,
		);
	});

	it("rolls back a registered partial worktree when atomic creation fails", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-lf-${process.pid}-${Date.now()}`;
		const label = "agent-deadbe/worker";
		const worktreeDir = path.join(WORKTREES_ROOT, repoName, "agent-deadbe", "worker");
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		let listCalls = 0;
		const calls: string[][] = [];
		const pi = execPi((args) => {
			if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
				listCalls++;
				const partial = `worktree ${worktreeDir}\nbranch refs/heads/${label}\nlocked basecamp agent run\n\n`;
				return { code: 0, stdout: listCalls === 1 ? `worktree ${repoRoot}\n\n` : partial, stderr: "" };
			}
			if (args.includes("add")) return { code: 1, stdout: "", stderr: "fatal: atomic add failed" };
			return { code: 0, stdout: "", stderr: "" };
		}, calls);

		await assert.rejects(() => createAgentWorktree(pi, repoRoot, repoName, label, "HEAD"), /atomic add failed/);
		const removeIndex = calls.findIndex((args) => args.includes("remove"));
		const deleteIndex = calls.findIndex((args) => args.includes("-D"));
		assert.notEqual(removeIndex, -1, "removes the partial worktree");
		assert.ok(calls[removeIndex]?.includes("--force"), "force-removes pre-execution residue");
		assert.notEqual(deleteIndex, -1, "deletes the partial branch");
		assert.ok(removeIndex < deleteIndex, "removes the worktree before deleting its branch");
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

	it("can remove without unlocking first", async () => {
		const calls: string[][] = [];
		const pi = execPi(() => ({ code: 0, stdout: "", stderr: "" }), calls);
		await removeWorktree(pi, "/repo", "/wt", { unlock: false });

		assert.equal(
			calls.some((args) => args.includes("unlock")),
			false,
		);
		assert.ok(calls.some((args) => args.includes("remove")));
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
