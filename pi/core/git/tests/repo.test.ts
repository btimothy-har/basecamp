import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { deriveRepoIdentity, resolveGitInfo, resolveReviewBase } from "#core/git/repo.ts";

interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

type ExecResult = { code: number; stdout: string; stderr: string };

function argsEqual(actual: string[], expected: string[]): boolean {
	return actual.length === expected.length && actual.every((arg, index) => arg === expected[index]);
}

function createPi(handler: (call: ExecCall) => ExecResult | Promise<ExecResult>): ExtensionAPI {
	return {
		exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult> {
			return Promise.resolve(handler({ command, args, options }));
		},
	} as ExtensionAPI;
}

describe("deriveRepoIdentity", () => {
	it("derives identities from scp-like remotes", () => {
		assert.equal(deriveRepoIdentity("git@github.com:org/name.git", "fallback"), "org/name");
	});

	it("derives identities from ssh URL remotes", () => {
		assert.equal(deriveRepoIdentity("ssh://git@github.com/org/name.git", "fallback"), "org/name");
	});

	it("derives identities from https URL remotes without .git", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name", "fallback"), "org/name");
	});

	it("derives identities from https URL remotes with .git", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name.git", "fallback"), "org/name");
	});

	it("derives identities from remotes ending in .git with a trailing slash", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name.git/", "fallback"), "org/name");
	});

	it("falls back for hostless/raw paths and dot segments", () => {
		assert.equal(deriveRepoIdentity("../repo.git", "fallback"), "fallback");
		assert.equal(deriveRepoIdentity("/local/path/repo.git", "fallback"), "fallback");
	});

	it("derives identities from non-GitHub hosts", () => {
		assert.equal(deriveRepoIdentity("git@gitlab.com:group/sub.git", "fallback"), "group/sub");
	});

	it("falls back without a remote", () => {
		assert.equal(deriveRepoIdentity(null, "fallback"), "fallback");
	});

	it("falls back with an empty remote", () => {
		assert.equal(deriveRepoIdentity("", "fallback"), "fallback");
		assert.equal(deriveRepoIdentity("  ", "fallback"), "fallback");
	});

	it("falls back for a single-segment unparseable path", () => {
		assert.equal(deriveRepoIdentity("not-a-url", "fallback"), "fallback");
	});
});

describe("resolveReviewBase", () => {
	const repoRoot = path.resolve("/repos/repo");
	const MERGE_BASE = "abc123mergebase";

	function pi(options: { originHead?: string; hasRemoteRef?: boolean; expectRef: string }): ExtensionAPI {
		return createPi((call) => {
			assert.equal(call.command, "git");
			if (argsEqual(call.args, ["-C", repoRoot, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])) {
				return options.originHead
					? { code: 0, stdout: `${options.originHead}\n`, stderr: "" }
					: { code: 1, stdout: "", stderr: "" };
			}
			if (call.args[2] === "rev-parse") {
				const ref = call.args[4];
				const known = options.hasRemoteRef !== false && ref === options.expectRef;
				return known || ref === "main" ? { code: 0, stdout: "sha\n", stderr: "" } : { code: 1, stdout: "", stderr: "" };
			}
			if (argsEqual(call.args, ["-C", repoRoot, "merge-base", options.expectRef, "HEAD"])) {
				return { code: 0, stdout: `${MERGE_BASE}\n`, stderr: "" };
			}
			throw new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
		});
	}

	it("prefers the remote-tracking ref, since nothing here ever fetches", async () => {
		// A local `main` left behind by an earlier pull would place the base before
		// the real branch point and pull upstream commits into the review.
		const result = await resolveReviewBase(pi({ originHead: "origin/main", expectRef: "origin/main" }), repoRoot);

		assert.equal(result, MERGE_BASE);
	});

	it("falls back to the local branch when no remote-tracking ref exists", async () => {
		const result = await resolveReviewBase(
			pi({ originHead: "origin/main", hasRemoteRef: false, expectRef: "main" }),
			repoRoot,
		);

		assert.equal(result, MERGE_BASE);
	});

	it("surfaces the existing error when the default branch cannot be detected", async () => {
		const failing = createPi(() => ({ code: 1, stdout: "", stderr: "" }));

		await assert.rejects(() => resolveReviewBase(failing, repoRoot), /Could not determine default branch/);
	});
});

describe("resolveGitInfo", () => {
	const remoteUrl = "git@github.com:test/repo.git";

	it("detects linked worktrees from distinct git dir and common dir", async () => {
		const mainRoot = path.resolve("/repos/repo");
		const worktreeRoot = path.resolve("/worktrees/test/repo/feature");
		const cwd = path.join(worktreeRoot, "packages", "app");
		const pi = createPi((call) => {
			assert.equal(call.command, "git");
			if (argsEqual(call.args, ["rev-parse", "--show-toplevel"])) {
				return { code: 0, stdout: `${worktreeRoot}\n`, stderr: "" };
			}
			if (argsEqual(call.args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				return {
					code: 0,
					stdout: `${path.join(mainRoot, ".git", "worktrees", "feature")}\n${path.join(mainRoot, ".git")}\n`,
					stderr: "",
				};
			}
			if (argsEqual(call.args, ["-C", worktreeRoot, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${remoteUrl}\n`, stderr: "" };
			}
			throw new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
		});

		assert.deepEqual(await resolveGitInfo(pi, cwd), {
			repoName: "test/repo",
			isRepo: true,
			remoteUrl,
			toplevel: worktreeRoot,
			mainRoot,
			isLinkedWorktree: true,
		});
	});

	it("detects normal checkouts from matching git dir and common dir", async () => {
		const repoRoot = path.resolve("/repos/repo");
		const pi = createPi((call) => {
			assert.equal(call.command, "git");
			if (argsEqual(call.args, ["rev-parse", "--show-toplevel"])) {
				return { code: 0, stdout: `${repoRoot}\n`, stderr: "" };
			}
			if (argsEqual(call.args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				return { code: 0, stdout: `${path.join(repoRoot, ".git")}\n${path.join(repoRoot, ".git")}\n`, stderr: "" };
			}
			if (argsEqual(call.args, ["-C", repoRoot, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${remoteUrl}\n`, stderr: "" };
			}
			throw new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
		});

		assert.deepEqual(await resolveGitInfo(pi, path.join(repoRoot, "src")), {
			repoName: "test/repo",
			isRepo: true,
			remoteUrl,
			toplevel: repoRoot,
			mainRoot: repoRoot,
			isLinkedWorktree: false,
		});
	});

	it("falls back gracefully when linked-worktree detection fails", async () => {
		const repoRoot = path.resolve("/repos/repo");
		const pi = createPi((call) => {
			assert.equal(call.command, "git");
			if (argsEqual(call.args, ["rev-parse", "--show-toplevel"])) {
				return { code: 0, stdout: `${repoRoot}\n`, stderr: "" };
			}
			if (argsEqual(call.args, ["rev-parse", "--git-dir", "--git-common-dir"])) {
				throw new Error("rev-parse failed");
			}
			if (argsEqual(call.args, ["-C", repoRoot, "remote", "get-url", "origin"])) {
				return { code: 0, stdout: `${remoteUrl}\n`, stderr: "" };
			}
			throw new Error(`Unexpected exec call: ${call.command} ${JSON.stringify(call.args)}`);
		});

		assert.deepEqual(await resolveGitInfo(pi, repoRoot), {
			repoName: "test/repo",
			isRepo: true,
			remoteUrl,
			toplevel: repoRoot,
			mainRoot: repoRoot,
			isLinkedWorktree: false,
		});
	});

	it("returns null mainRoot for non-repositories", async () => {
		const cwd = path.resolve("/not-a-repo");
		const pi = createPi((call) => {
			assert.equal(call.command, "git");
			assert.ok(argsEqual(call.args, ["rev-parse", "--show-toplevel"]));
			return { code: 128, stdout: "", stderr: "fatal: not a git repository" };
		});

		assert.deepEqual(await resolveGitInfo(pi, cwd), {
			repoName: "not-a-repo",
			isRepo: false,
			remoteUrl: null,
			toplevel: null,
			mainRoot: null,
			isLinkedWorktree: false,
		});
	});
});
