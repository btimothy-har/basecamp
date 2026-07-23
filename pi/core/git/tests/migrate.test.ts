import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { worktreesRoot } from "../constants.ts";
import { migrateLegacyWorktrees, planLegacyWorktreeMigration, shouldRetryMoveWithForce } from "../worktrees/migrate.ts";
import { useTempWorktreesRoot } from "./worktree-root.ts";

useTempWorktreesRoot();

const REPO_NAME = "repo";
const IDENTITY = "org/repo";
const MAIN_PATH = path.join("/src", REPO_NAME);
const LEGACY_ROOT = path.join(worktreesRoot(), REPO_NAME);
const NEW_ROOT = path.join(worktreesRoot(), IDENTITY);

type WorktreeRecord = { path: string; branch: string | null };

function records(...paths: string[]): WorktreeRecord[] {
	return [MAIN_PATH, ...paths].map((worktreePath) => ({ path: worktreePath, branch: null }));
}

describe("planLegacyWorktreeMigration", () => {
	it("never moves the main worktree", () => {
		assert.deepEqual(
			planLegacyWorktreeMigration({
				records: [{ path: path.join(worktreesRoot(), REPO_NAME, "main-ish"), branch: "main" }],
				identity: IDENTITY,
				cwd: MAIN_PATH,
			}),
			{ moves: [] },
		);
	});

	it("plans direct legacy labels under the canonical identity root", () => {
		const src = path.join(LEGACY_ROOT, "feature");

		assert.deepEqual(planLegacyWorktreeMigration({ records: records(src), identity: IDENTITY, cwd: MAIN_PATH }), {
			moves: [{ src, dest: path.join(NEW_ROOT, "feature"), label: "feature" }],
		});
	});

	it("plans nested legacy labels under the canonical identity root", () => {
		const src = path.join(LEGACY_ROOT, "wt-bt", "feat");

		assert.deepEqual(planLegacyWorktreeMigration({ records: records(src), identity: IDENTITY, cwd: MAIN_PATH }), {
			moves: [{ src, dest: path.join(NEW_ROOT, "wt-bt", "feat"), label: "wt-bt/feat" }],
		});
	});

	it("excludes the active worktree when cwd is inside it", () => {
		const active = path.join(LEGACY_ROOT, "feature");
		const inactive = path.join(LEGACY_ROOT, "other");

		assert.deepEqual(
			planLegacyWorktreeMigration({
				records: records(active, inactive),
				identity: IDENTITY,
				cwd: path.join(active, "packages", "app"),
			}),
			{ moves: [{ src: inactive, dest: path.join(NEW_ROOT, "other"), label: "other" }] },
		);
	});

	it("excludes records already under the new root when org matches the bare name", () => {
		const identity = "repo/sub";
		const alreadyMigrated = path.join(worktreesRoot(), identity, "feature");
		const legacy = path.join(LEGACY_ROOT, "other");

		assert.deepEqual(
			planLegacyWorktreeMigration({ records: records(alreadyMigrated, legacy), identity, cwd: MAIN_PATH }),
			{
				moves: [{ src: legacy, dest: path.join(worktreesRoot(), identity, "other"), label: "other" }],
			},
		);
	});

	it("excludes non-legacy paths", () => {
		const outside = path.join(worktreesRoot(), "other", "feature");

		assert.deepEqual(planLegacyWorktreeMigration({ records: records(outside), identity: IDENTITY, cwd: MAIN_PATH }), {
			moves: [],
		});
	});

	it("returns no moves for identities without an org", () => {
		const src = path.join(LEGACY_ROOT, "feature");

		assert.deepEqual(planLegacyWorktreeMigration({ records: records(src), identity: REPO_NAME, cwd: MAIN_PATH }), {
			moves: [],
		});
	});
});

describe("shouldRetryMoveWithForce", () => {
	it("retries dirty worktree errors", () => {
		assert.equal(shouldRetryMoveWithForce("fatal: contains modified or untracked files; use --force to move"), true);
		assert.equal(shouldRetryMoveWithForce("worktree contains modified files"), true);
		assert.equal(shouldRetryMoveWithForce("modified or untracked files would be overwritten"), true);
	});

	it("does not retry locked worktrees", () => {
		assert.equal(shouldRetryMoveWithForce("fatal: worktree is locked; use --force to move"), false);
	});

	it("does not retry unrelated errors", () => {
		assert.equal(shouldRetryMoveWithForce("fatal: invalid path"), false);
	});
});

describe("migrateLegacyWorktrees legacy-root cleanup", () => {
	type ExecResult = { code: number; stdout: string; stderr: string };

	function migratePi(listBlocks: string[]): ExtensionAPI {
		const listOut = [`worktree ${MAIN_PATH}`, "branch refs/heads/main", "", ...listBlocks].join("\n");
		return {
			async exec(command: string, args: string[]): Promise<ExecResult> {
				assert.equal(command, "git");
				if (args.includes("list")) return { code: 0, stdout: listOut, stderr: "" };
				if (args.includes("move")) {
					// Simulate git's move so the source empties out, exercising the rmdir.
					fs.renameSync(args[args.length - 2] ?? "", args[args.length - 1] ?? "");
					return { code: 0, stdout: "", stderr: "" };
				}
				throw new Error(`unexpected git ${JSON.stringify(args)}`);
			},
		} as ExtensionAPI;
	}

	function worktreeBlock(dir: string, branch: string): string[] {
		return [`worktree ${dir}`, `branch refs/heads/${branch}`, ""];
	}

	it("rmdirs the legacy root once its worktrees have moved out", async (t) => {
		t.after(() => fs.rmSync(worktreesRoot(), { recursive: true, force: true }));
		const src = path.join(LEGACY_ROOT, "feature");
		fs.mkdirSync(src, { recursive: true });
		const pi = migratePi(worktreeBlock(src, "wt/feature"));

		const result = await migrateLegacyWorktrees(pi, { repoRoot: MAIN_PATH, identity: IDENTITY, cwd: "/elsewhere" });

		assert.deepEqual(result.moved, ["feature"]);
		assert.equal(fs.existsSync(LEGACY_ROOT), false, "emptied legacy root is removed");
		assert.equal(fs.existsSync(path.join(NEW_ROOT, "feature")), true);
	});

	it("keeps a legacy root that still holds a skipped worktree", async (t) => {
		t.after(() => fs.rmSync(worktreesRoot(), { recursive: true, force: true }));
		const moved = path.join(LEGACY_ROOT, "feature");
		const skipped = path.join(LEGACY_ROOT, "other");
		fs.mkdirSync(moved, { recursive: true });
		fs.mkdirSync(skipped, { recursive: true });
		// Pre-create the destination for "other" so its move is skipped, leaving residue behind.
		fs.mkdirSync(path.join(NEW_ROOT, "other"), { recursive: true });
		const pi = migratePi([...worktreeBlock(moved, "wt/feature"), ...worktreeBlock(skipped, "wt/other")]);

		const result = await migrateLegacyWorktrees(pi, { repoRoot: MAIN_PATH, identity: IDENTITY, cwd: "/elsewhere" });

		assert.deepEqual(result.moved, ["feature"]);
		assert.equal(result.skipped.length, 1);
		assert.equal(fs.existsSync(LEGACY_ROOT), true, "a legacy root with residue is left intact");
		assert.equal(fs.existsSync(skipped), true);
	});
});
