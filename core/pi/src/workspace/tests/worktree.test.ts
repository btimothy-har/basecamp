import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { WORKTREES_ROOT } from "../constants.ts";
import {
	branchName,
	ensureWorktreeLabel,
	findWorktreeRecord,
	labelFromWorktreePath,
	parseWorktreeList,
	validateNoSymlinkedWorktreePath,
	validateWorktreePath,
} from "../worktree.ts";

const REPO_NAME = "repo";
const LABEL = "feature-1";
const WORKTREE_DIR = path.join(WORKTREES_ROOT, REPO_NAME, LABEL);

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
				{ path: "/repo", branch: "main" },
				{ path: WORKTREE_DIR, branch: "wt/feature-1" },
			]);
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
				{ path: "/repo", branch: "main" },
				{ path: `${WORKTREE_DIR}${path.sep}`, branch: "wt/feature-1" },
			];

			assert.deepEqual(findWorktreeRecord(records, WORKTREE_DIR), records[1]);
			assert.deepEqual(findWorktreeRecord(records, `${WORKTREE_DIR}${path.sep}`), records[1]);
			assert.equal(findWorktreeRecord(records, path.join(WORKTREES_ROOT, REPO_NAME, "missing")), null);
		});
	});

	describe("ensureWorktreeLabel", () => {
		it("accepts valid labels", () => {
			for (const label of ["feature", "Feature.1", "bug_fix-2", "a"]) {
				assert.doesNotThrow(() => ensureWorktreeLabel(label));
			}
		});

		it("rejects invalid labels", () => {
			for (const label of ["", "-feature", ".feature", "feature/name", "feature name"]) {
				assert.throws(() => ensureWorktreeLabel(label), /Invalid worktree label/);
			}
		});
	});

	describe("labelFromWorktreePath", () => {
		it("returns labels for direct children under WORKTREES_ROOT/repo", () => {
			assert.equal(labelFromWorktreePath(REPO_NAME, WORKTREE_DIR), LABEL);
			assert.equal(labelFromWorktreePath(REPO_NAME, `${WORKTREE_DIR}${path.sep}`), LABEL);
		});

		it("requires worktrees to be directly under WORKTREES_ROOT/repo", () => {
			const repoRoot = path.join(WORKTREES_ROOT, REPO_NAME);

			assert.throws(() => labelFromWorktreePath(REPO_NAME, repoRoot), /directly under/);
			assert.throws(() => labelFromWorktreePath(REPO_NAME, path.join(repoRoot, LABEL, "nested")), /directly under/);
			assert.throws(
				() => labelFromWorktreePath(REPO_NAME, path.join(WORKTREES_ROOT, "other", LABEL)),
				/directly under/,
			);
		});
	});

	describe("validateWorktreePath", () => {
		it("allows the expected worktree path", () => {
			assert.doesNotThrow(() => validateWorktreePath(REPO_NAME, LABEL, `${WORKTREE_DIR}${path.sep}`));
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
