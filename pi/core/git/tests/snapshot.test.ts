import assert from "node:assert/strict";
import { execFile, execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createSnapshotCommit } from "../repo.ts";

type ExecResult = { code: number; stdout: string; stderr: string };

/** Real subprocess execution — the snapshot helper's correctness rides on git plumbing semantics. */
function realPi(): ExtensionAPI {
	return {
		async exec(cmd: string, args: string[], opts?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			return await new Promise<ExecResult>((resolve) => {
				execFile(cmd, args, { cwd: opts?.cwd, timeout: opts?.timeout }, (error, stdout, stderr) => {
					const code = error ? (typeof error.code === "number" ? error.code : 1) : 0;
					resolve({ code, stdout, stderr });
				});
			});
		},
	} as unknown as ExtensionAPI;
}

function git(repo: string, ...args: string[]): string {
	return execFileSync("git", ["-C", repo, ...args], { encoding: "utf-8" }).trim();
}

function initRepo(t: { after(fn: () => void): void }): string {
	const repo = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-snapshot-"));
	t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
	git(repo, "init", "-q", "-b", "main");
	git(repo, "config", "user.email", "t@t");
	git(repo, "config", "user.name", "t");
	fs.writeFileSync(path.join(repo, "tracked.txt"), "original\n");
	fs.writeFileSync(path.join(repo, ".gitignore"), "ignored.txt\n");
	git(repo, "add", "-A");
	git(repo, "commit", "-q", "-m", "init");
	return repo;
}

describe("createSnapshotCommit (real git)", () => {
	it("captures tracked+untracked state without touching the tree, index, or HEAD", async (t) => {
		const repo = initRepo(t);
		fs.writeFileSync(path.join(repo, "tracked.txt"), "modified\n");
		fs.writeFileSync(path.join(repo, "untracked.txt"), "new\n");
		fs.writeFileSync(path.join(repo, "ignored.txt"), "secret\n");
		const headBefore = git(repo, "rev-parse", "HEAD");
		const statusBefore = git(repo, "status", "--porcelain");

		const snapshot = await createSnapshotCommit(realPi(), repo);

		assert.equal(git(repo, "rev-parse", "HEAD"), headBefore, "HEAD untouched");
		assert.equal(git(repo, "status", "--porcelain"), statusBefore, "tree and index untouched");
		assert.equal(git(repo, "rev-parse", `${snapshot}^`), headBefore, "snapshot parented on HEAD");
		assert.equal(git(repo, "show", `${snapshot}:tracked.txt`), "modified", "captures modified tracked content");
		assert.equal(git(repo, "show", `${snapshot}:untracked.txt`), "new", "captures untracked files");
		const tree = git(repo, "ls-tree", "--name-only", snapshot);
		assert.ok(!tree.includes("ignored.txt"), "gitignored files stay out of the snapshot");
	});

	it("captures deletions of tracked files", async (t) => {
		const repo = initRepo(t);
		fs.writeFileSync(path.join(repo, "doomed.txt"), "bye\n");
		git(repo, "add", "-A");
		git(repo, "commit", "-q", "-m", "add doomed");
		fs.rmSync(path.join(repo, "doomed.txt"));

		const snapshot = await createSnapshotCommit(realPi(), repo);

		const tree = git(repo, "ls-tree", "--name-only", snapshot);
		assert.ok(tree.includes("tracked.txt"));
		assert.ok(!tree.includes("doomed.txt"), "deleted tracked file absent from the snapshot");
	});
});
