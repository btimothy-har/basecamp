import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREES_ROOT } from "../constants.ts";
import {
	branchName,
	ensureWorktreeLabel,
	findWorktreeRecord,
	getOrCreateWorktree,
	labelFromWorktreePath,
	parseWorktreeList,
	validateNoSymlinkedWorktreePath,
	validateWorktreePath,
} from "../worktrees/crud.ts";

const REPO_NAME = "repo";
const SLASHED_REPO_NAME = "org/repo";
const LABEL = "feature-1";
const NESTED_LABEL = "wt-bt/feature-1";
const WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_NAME, LABEL);
const NESTED_WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_NAME, "wt-bt", "feature-1");
const SLASHED_WORKTREE_DIR = path.join(WORKTREES_ROOT, "org", "repo", LABEL);
const SLASHED_NESTED_WORKTREE_DIR = path.join(WORKTREES_ROOT, "org", "repo", "wt-bt", "feature-1");

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
			if (argsEqual(args, ["-C", repoRoot, "status", "--porcelain"])) {
				return { code: 0, stdout: "", stderr: "" };
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

describe("worktree pure utilities", () => {
	describe("parseWorktreeList", () => {
		it("strips refs/heads prefixes and parses multiple records", () => {
			const records = parseWorktreeList(
				[
					"worktree /repo",
					"HEAD abc123",
					"branch refs/heads/main",
					"",
					`worktree ${WORKTREE_DIR}`,
					"HEAD def456",
					"branch refs/heads/wt/feature-1",
				].join("\n"),
			);

			assert.deepEqual(records, [
				{ path: "/repo", branch: "main", locked: false },
				{ path: WORKTREE_DIR, branch: "wt/feature-1", locked: false },
			]);
		});

		it("parses locks with and without reasons", () => {
			const records = parseWorktreeList(
				[
					"worktree /locked-without-reason",
					"HEAD abc123",
					"locked",
					"",
					"worktree /locked-with-reason",
					"HEAD def456",
					"locked basecamp agent run",
				].join("\n"),
			);

			assert.equal(records[0]?.locked, true);
			assert.equal(records[1]?.locked, true);
		});

		it("returns no records for empty or blank output", () => {
			assert.deepEqual(parseWorktreeList(""), []);
			assert.deepEqual(parseWorktreeList("\n\n  \n"), []);
		});

		it("preserves raw branch values without refs/heads prefix", () => {
			const [record] = parseWorktreeList([`worktree ${WORKTREE_DIR}`, "branch wt/raw"].join("\n"));

			assert.equal(record?.branch, "wt/raw");
		});

		it("leaves missing branch records detached", () => {
			const [record] = parseWorktreeList([`worktree ${WORKTREE_DIR}`, "HEAD abc123"].join("\n"));

			assert.equal(record?.branch, null);
			assert.equal(branchName(record), "detached");
		});
	});

	describe("findWorktreeRecord", () => {
		it("matches resolved paths and ignores trailing slash differences", () => {
			const records = [
				{ path: "/repo", branch: "main", locked: false },
				{ path: `${WORKTREE_DIR}${path.sep}`, branch: "wt/feature-1", locked: false },
			];

			assert.deepEqual(findWorktreeRecord(records, WORKTREE_DIR), records[1]);
			assert.deepEqual(findWorktreeRecord(records, `${WORKTREE_DIR}${path.sep}`), records[1]);
			assert.equal(findWorktreeRecord(records, path.join(WORKTREES_ROOT, REPO_NAME, "missing")), null);
		});
	});

	describe("ensureWorktreeLabel", () => {
		it("accepts valid labels", () => {
			for (const label of [
				"feature",
				"Feature.1",
				"bug_fix-2",
				"a",
				"wt-bt/feature",
				"wt-b1/Feature.1",
				"copilot/steady-amber-otter",
				"copilot/feature",
				"agent-3f9a2c/worker",
				"agent-a1b2c3d4/adhoc",
			]) {
				assert.doesNotThrow(() => ensureWorktreeLabel(label));
			}
		});

		it("rejects invalid labels", () => {
			for (const label of [
				"",
				"-feature",
				".feature",
				"feature/name",
				"feature name",
				"wt-b/feature",
				"wt-bt/",
				"wt-bt/-feature",
				"wt-bt/feature name",
				"wt-bt/feature/nested",
				"copilot/",
				"copilot/-feature",
				"copilot/feature name",
				"copilot/feature/nested",
				"Copilot/feature",
			]) {
				assert.throws(() => ensureWorktreeLabel(label), /Invalid worktree label/);
			}
		});
	});

	describe("labelFromWorktreePath", () => {
		it("returns labels for direct children under WORKTREES_ROOT/repo", () => {
			assert.equal(labelFromWorktreePath(REPO_NAME, WORKTREE_DIR), LABEL);
			assert.equal(labelFromWorktreePath(REPO_NAME, `${WORKTREE_DIR}${path.sep}`), LABEL);
		});

		it("returns nested execution worktree labels under WORKTREES_ROOT/repo", () => {
			assert.equal(labelFromWorktreePath(REPO_NAME, NESTED_WORKTREE_DIR), NESTED_LABEL);
			assert.equal(labelFromWorktreePath(REPO_NAME, `${NESTED_WORKTREE_DIR}${path.sep}`), NESTED_LABEL);
		});

		it("round-trips direct and nested labels for slashed repo identities", () => {
			assert.equal(path.join(WORKTREES_ROOT, SLASHED_REPO_NAME, LABEL), SLASHED_WORKTREE_DIR);
			assert.equal(labelFromWorktreePath(SLASHED_REPO_NAME, SLASHED_WORKTREE_DIR), LABEL);
			assert.equal(labelFromWorktreePath(SLASHED_REPO_NAME, SLASHED_NESTED_WORKTREE_DIR), NESTED_LABEL);
		});

		it("requires worktrees to use valid workspace paths", () => {
			const repoRoot = path.join(WORKTREES_ROOT, REPO_NAME);

			assert.throws(() => labelFromWorktreePath(REPO_NAME, repoRoot), /valid workspace worktree path/);
			assert.throws(
				() => labelFromWorktreePath(REPO_NAME, path.join(repoRoot, LABEL, "nested")),
				/valid workspace worktree path/,
			);
			assert.throws(
				() => labelFromWorktreePath(REPO_NAME, path.join(repoRoot, "wt-bt", LABEL, "nested")),
				/valid workspace worktree path/,
			);
			assert.throws(
				() => labelFromWorktreePath(REPO_NAME, path.join(WORKTREES_ROOT, "other", LABEL)),
				/valid workspace worktree path/,
			);
		});
	});

	describe("validateWorktreePath", () => {
		it("allows the expected worktree path", () => {
			assert.doesNotThrow(() => validateWorktreePath(REPO_NAME, LABEL, `${WORKTREE_DIR}${path.sep}`));
			assert.doesNotThrow(() => validateWorktreePath(REPO_NAME, NESTED_LABEL, `${NESTED_WORKTREE_DIR}${path.sep}`));
		});

		it("rejects mismatched paths with the expected path", () => {
			assert.throws(
				() => validateWorktreePath(REPO_NAME, LABEL, path.join(WORKTREES_ROOT, REPO_NAME, "different")),
				new RegExp(`Worktree path must be ${WORKTREE_DIR.replaceAll("\\", "\\\\")}`),
			);
		});
	});

	describe("validateNoSymlinkedWorktreePath", () => {
		function createTempRoot(t: { after(fn: () => void): void }): string {
			const root = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-worktrees-"));
			t.after(() => fs.rmSync(root, { recursive: true, force: true }));
			return root;
		}

		it("allows normal worktree paths", (t) => {
			const root = createTempRoot(t);
			const worktreeDir = path.join(root, REPO_NAME, LABEL);
			fs.mkdirSync(worktreeDir, { recursive: true });

			assert.doesNotThrow(() => validateNoSymlinkedWorktreePath(worktreeDir, root));
		});

		it("allows missing leaf paths for new worktree creation", (t) => {
			const root = createTempRoot(t);
			fs.mkdirSync(path.join(root, REPO_NAME), { recursive: true });

			assert.doesNotThrow(() => validateNoSymlinkedWorktreePath(path.join(root, REPO_NAME, LABEL), root));
			assert.doesNotThrow(() => validateNoSymlinkedWorktreePath(path.join(root, REPO_NAME, "wt-bt", LABEL), root));
		});

		it("rejects symlinked worktree directories", (t) => {
			const root = createTempRoot(t);
			const repoRoot = path.join(root, REPO_NAME);
			const realWorktree = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-real-worktree-"));
			t.after(() => fs.rmSync(realWorktree, { recursive: true, force: true }));
			fs.mkdirSync(repoRoot, { recursive: true });

			const symlinkedWorktree = path.join(repoRoot, LABEL);
			fs.symlinkSync(realWorktree, symlinkedWorktree, "dir");

			assert.throws(
				() => validateNoSymlinkedWorktreePath(symlinkedWorktree, root),
				/Worktree path must not contain symlinks/,
			);
		});

		it("rejects symlinked parent directories", (t) => {
			const root = createTempRoot(t);
			const realRepo = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-real-repo-"));
			t.after(() => fs.rmSync(realRepo, { recursive: true, force: true }));

			const symlinkedRepo = path.join(root, REPO_NAME);
			fs.symlinkSync(realRepo, symlinkedRepo, "dir");

			assert.throws(
				() => validateNoSymlinkedWorktreePath(path.join(symlinkedRepo, LABEL), root),
				/Worktree path must not contain symlinks/,
			);
		});
	});
});

describe("getOrCreateWorktree", () => {
	it("creates nested execution worktrees with an explicit branch", async (t) => {
		const repoRoot = "/repo";
		const repoName = `repo-explicit-${process.pid}-${Date.now()}`;
		const label = "wt-bt/new-work";
		const branch = "bt/new-work";
		const worktreeDir = path.join(WORKTREES_ROOT, repoName, "wt-bt", "new-work");
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

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
		const worktreeDir = path.join(WORKTREES_ROOT, repoName, label);
		t.after(() => fs.rmSync(path.join(WORKTREES_ROOT, repoName), { recursive: true, force: true }));

		const expectedAddArgs = ["-C", repoRoot, "worktree", "add", "-b", branch, worktreeDir, "main"];
		const { pi, calls } = createWorktreePi(repoRoot, expectedAddArgs);

		const result = await getOrCreateWorktree(pi, repoRoot, repoName, label);

		assert.deepEqual(result, { worktreeDir, label, branch, created: true });
		assert.ok(calls.some((args) => argsEqual(args, expectedAddArgs)));
	});
});
