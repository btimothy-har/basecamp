import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "#core/git/constants.ts";
import {
	getOrCreateWorktree,
	resolveAvailableWorktreeLabel,
	validateProtectedCheckout,
} from "#core/git/worktrees/crud.ts";
import { useTempWorktreesRoot } from "./worktree-root.ts";

useTempWorktreesRoot();

type ExecResult = { code: number; stdout: string; stderr: string };

function argsEqual(actual: string[], expected: string[]): boolean {
	return actual.length === expected.length && actual.every((arg, index) => arg === expected[index]);
}

function createWorktreePi(repoRoot: string, expectedAddArgs: string[]): { pi: ExtensionAPI; calls: string[][] } {
	const calls: string[][] = [];
	const pi = {
		async exec(command: string, args: string[]): Promise<ExecResult> {
			calls.push(args);
			assert.equal(command, "git");

			if (argsEqual(args, ["-C", repoRoot, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
				return { code: 0, stdout: "origin/main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", repoRoot, "branch", "--show-current"])) {
				return { code: 0, stdout: "main\n", stderr: "" };
			}
			if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
				return { code: 0, stdout: `worktree ${repoRoot}\nbranch refs/heads/main\n\n`, stderr: "" };
			}
			if (args[0] === "-C" && args[1] === repoRoot && args[2] === "rev-parse") {
				return { code: 1, stdout: "", stderr: "missing" };
			}
			if (argsEqual(args, expectedAddArgs)) {
				return { code: 0, stdout: "", stderr: "" };
			}

			throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
		},
	} as ExtensionAPI;
	return { pi, calls };
}

describe("getOrCreateWorktree", () => {
	it("creates nested execution worktrees with an explicit branch", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-explicit-${process.pid}-${Date.now()}`;
		const label = "wt-bt/new-work";
		const branch = "bt/new-work";
		const worktreeDir = path.join(worktreesRoot(), repoName, "wt-bt", "new-work");
		t.after(() => fs.rmSync(path.join(worktreesRoot(), repoName), { recursive: true, force: true }));

		const expectedAddArgs = ["-C", repoRoot, "worktree", "add", "-b", branch, worktreeDir, "main"];
		const { pi, calls } = createWorktreePi(repoRoot, expectedAddArgs);

		const result = await getOrCreateWorktree(pi, repoRoot, repoName, label, branch);

		assert.deepEqual(result, { worktreeDir, label, branch, created: true });
		assert.ok(calls.some((args) => argsEqual(args, expectedAddArgs)));
	});

	it("keeps deriving wt branches when no explicit branch is provided", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-default-${process.pid}-${Date.now()}`;
		const label = "feature-1";
		const branch = "wt/feature-1";
		const worktreeDir = path.join(worktreesRoot(), repoName, label);
		t.after(() => fs.rmSync(path.join(worktreesRoot(), repoName), { recursive: true, force: true }));

		const expectedAddArgs = ["-C", repoRoot, "worktree", "add", "-b", branch, worktreeDir, "main"];
		const { pi, calls } = createWorktreePi(repoRoot, expectedAddArgs);

		const result = await getOrCreateWorktree(pi, repoRoot, repoName, label);

		assert.deepEqual(result, { worktreeDir, label, branch, created: true });
		assert.ok(calls.some((args) => argsEqual(args, expectedAddArgs)));
	});

	it("locks a newly created worktree atomically when a lock reason is given", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-lock-${process.pid}-${Date.now()}`;
		const label = "copilot/steady-otter";
		const branch = "bt/steady-otter";
		const reason = "basecamp staged 2026-07-29T00:00:00.000Z";
		const worktreeDir = path.join(worktreesRoot(), repoName, "copilot", "steady-otter");
		t.after(() => fs.rmSync(path.join(worktreesRoot(), repoName), { recursive: true, force: true }));

		const expectedAddArgs = [
			"-C",
			repoRoot,
			"worktree",
			"add",
			"--lock",
			"--reason",
			reason,
			"-b",
			branch,
			worktreeDir,
			"main",
		];
		const { pi, calls } = createWorktreePi(repoRoot, expectedAddArgs);

		const result = await getOrCreateWorktree(pi, repoRoot, repoName, label, branch, reason);

		assert.deepEqual(result, { worktreeDir, label, branch, created: true });
		assert.ok(calls.some((args) => argsEqual(args, expectedAddArgs)));
	});

	it("refuses to derive a branch for a namespaced label when the worktree is gone", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-adopt-${process.pid}-${Date.now()}`;
		t.after(() => fs.rmSync(path.join(worktreesRoot(), repoName), { recursive: true, force: true }));

		// Adopting a worktree that was reaped after the caller listed it: deriving `wt/` + `wt/gone`
		// would silently create a meaningless `wt/wt/gone` branch instead of the intended work.
		const { pi } = createWorktreePi(repoRoot, []);

		await assert.rejects(
			() => getOrCreateWorktree(pi, repoRoot, repoName, "wt/gone"),
			/no longer exists and no branch was given to rebuild it from/,
		);
	});
});

describe("validateProtectedCheckout", () => {
	function checkoutPi(repoRoot: string, currentBranch: string): ExtensionAPI {
		return {
			async exec(command: string, args: string[]): Promise<ExecResult> {
				assert.equal(command, "git");
				if (argsEqual(args, ["-C", repoRoot, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
					return { code: 0, stdout: "origin/main\n", stderr: "" };
				}
				if (argsEqual(args, ["-C", repoRoot, "branch", "--show-current"])) {
					return { code: 0, stdout: `${currentBranch}\n`, stderr: "" };
				}
				throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
			},
		} as ExtensionAPI;
	}

	it("returns the default branch without inspecting worktree status (a dirty checkout is allowed)", async () => {
		// The mock throws on any `status --porcelain` call, so this fails if the clean-clause is reintroduced.
		const defaultBranch = await validateProtectedCheckout(checkoutPi("/repo", "main"), "/repo");
		assert.equal(defaultBranch, "main");
	});

	it("throws when the checkout is not on the default branch", async () => {
		await assert.rejects(
			() => validateProtectedCheckout(checkoutPi("/repo", "feature"), "/repo"),
			/Protected checkout must be on main; currently on feature/,
		);
	});
});

describe("resolveAvailableWorktreeLabel", () => {
	const repoRoot = "/repo";

	function listPi(records: { label: string; branch: string }[], repoName: string): ExtensionAPI {
		const porcelain = [
			`worktree ${repoRoot}`,
			"branch refs/heads/main",
			"",
			...records.flatMap(({ label, branch }) => [
				`worktree ${path.join(worktreesRoot(), repoName, label)}`,
				`branch refs/heads/${branch}`,
				"",
			]),
		].join("\n");
		return {
			async exec(command: string, args: string[]): Promise<ExecResult> {
				assert.equal(command, "git");
				if (argsEqual(args, ["-C", repoRoot, "worktree", "list", "--porcelain"])) {
					return { code: 0, stdout: porcelain, stderr: "" };
				}
				throw new Error(`Unexpected git args: ${JSON.stringify(args)}`);
			},
		} as ExtensionAPI;
	}

	it("returns the base label when its directory is free", async () => {
		const repoName = `resolve-free-${process.pid}-${Date.now()}`;
		const label = await resolveAvailableWorktreeLabel(
			listPi([], repoName),
			repoRoot,
			repoName,
			"wt/foo",
			"bt/a1b2-foo",
		);
		assert.equal(label, "wt/foo");
	});

	it("returns the base label when it already holds the intended branch (resume)", async () => {
		const repoName = `resolve-same-${process.pid}-${Date.now()}`;
		const pi = listPi([{ label: "wt/foo", branch: "bt/a1b2-foo" }], repoName);
		const label = await resolveAvailableWorktreeLabel(pi, repoRoot, repoName, "wt/foo", "bt/a1b2-foo");
		assert.equal(label, "wt/foo");
	});

	it("suffixes when the base label is occupied by a different branch", async () => {
		const repoName = `resolve-diff-${process.pid}-${Date.now()}`;
		const pi = listPi([{ label: "wt/foo", branch: "bt/x1y2-foo" }], repoName);
		const label = await resolveAvailableWorktreeLabel(pi, repoRoot, repoName, "wt/foo", "bt/a1b2-foo");
		assert.equal(label, "wt/foo-2");
	});

	it("keeps incrementing past multiple different-branch collisions", async () => {
		const repoName = `resolve-multi-${process.pid}-${Date.now()}`;
		const pi = listPi(
			[
				{ label: "wt/foo", branch: "bt/x1y2-foo" },
				{ label: "wt/foo-2", branch: "bt/z9z9-foo" },
			],
			repoName,
		);
		const label = await resolveAvailableWorktreeLabel(pi, repoRoot, repoName, "wt/foo", "bt/a1b2-foo");
		assert.equal(label, "wt/foo-3");
	});
});
