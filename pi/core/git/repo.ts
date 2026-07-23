import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export async function gitOutput(pi: ExtensionAPI, repoRoot: string, args: string[], timeout = 10_000): Promise<string> {
	const result = await pi.exec("git", ["-C", repoRoot, ...args], { timeout });
	if (result.code !== 0) {
		throw new Error(result.stderr.trim() || `git ${args.join(" ")} failed`);
	}
	return result.stdout.trim();
}

export async function tryGitOutput(pi: ExtensionAPI, repoRoot: string, args: string[]): Promise<string | null> {
	try {
		return await gitOutput(pi, repoRoot, args);
	} catch {
		return null;
	}
}

export async function detectDefaultBranch(pi: ExtensionAPI, repoRoot: string): Promise<string> {
	const originHead = await tryGitOutput(pi, repoRoot, [
		"symbolic-ref",
		"--quiet",
		"--short",
		"refs/remotes/origin/HEAD",
	]);
	if (originHead?.startsWith("origin/")) return originHead.slice("origin/".length);
	if (await tryGitOutput(pi, repoRoot, ["rev-parse", "--verify", "main"])) return "main";
	if (await tryGitOutput(pi, repoRoot, ["rev-parse", "--verify", "master"])) return "master";
	throw new Error("Could not determine default branch (expected origin/HEAD, main, or master)");
}

export async function branchExists(pi: ExtensionAPI, repoRoot: string, branch: string): Promise<boolean> {
	return (await tryGitOutput(pi, repoRoot, ["rev-parse", "--verify", `refs/heads/${branch}`])) !== null;
}

/** Tip commit OID of a local branch, or null when the branch does not exist. */
export async function branchTip(pi: ExtensionAPI, repoRoot: string, branch: string): Promise<string | null> {
	return await tryGitOutput(pi, repoRoot, ["rev-parse", "--verify", "--quiet", `refs/heads/${branch}`]);
}

/** True if `branch` has been merged into `candidate` (is an ancestor of it). */
export async function isMergedInto(
	pi: ExtensionAPI,
	repoRoot: string,
	branch: string,
	candidate: string,
): Promise<boolean> {
	const result = await pi.exec("git", ["-C", repoRoot, "merge-base", "--is-ancestor", branch, candidate], {
		timeout: 15_000,
	});
	return result.code === 0;
}

/** True when the worktree has no uncommitted or untracked changes. */
export async function isWorktreeClean(pi: ExtensionAPI, worktreeDir: string): Promise<boolean> {
	return (await gitOutput(pi, worktreeDir, ["status", "--porcelain"])) === "";
}

const SNAPSHOT_TIMEOUT_MS = 60_000;

/**
 * Commit the worktree's current state (tracked + untracked, minus ignored) as a snapshot
 * object without touching the worktree's tree, index, or HEAD. Uses a throwaway index via
 * GIT_INDEX_FILE (through env(1), since pi.exec cannot set environment variables), so the
 * real index never sees the staging. Returns the snapshot commit OID, parented on HEAD.
 */
export async function createSnapshotCommit(pi: ExtensionAPI, worktreeDir: string): Promise<string> {
	const indexFile = path.join(os.tmpdir(), `basecamp-snapshot-${randomUUID()}.index`);
	const run = async (args: string[]): Promise<string> => {
		const result = await pi.exec("env", [`GIT_INDEX_FILE=${indexFile}`, "git", "-C", worktreeDir, ...args], {
			timeout: SNAPSHOT_TIMEOUT_MS,
		});
		if (result.code !== 0) {
			throw new Error(`Snapshot commit failed (git ${args[0]}): ${result.stderr.trim()}`);
		}
		return result.stdout.trim();
	};
	try {
		// Seed from HEAD so ignore rules only affect genuinely untracked files: with an empty
		// index, `add -A` would silently drop tracked-but-ignored files, recording them as
		// deletions in the snapshot tree.
		await run(["read-tree", "HEAD"]);
		await run(["add", "-A"]);
		const tree = await run(["write-tree"]);
		return await run(["commit-tree", tree, "-p", "HEAD", "-m", "basecamp dispatch snapshot"]);
	} finally {
		fs.rmSync(indexFile, { force: true });
	}
}

export function deriveRepoIdentity(remoteUrl: string | null, fallbackBasename: string): string {
	const trimmedRemoteUrl = remoteUrl?.trim();
	if (!trimmedRemoteUrl) return fallbackBasename;

	let pathPart: string | null = null;
	const scpLikeMatch = trimmedRemoteUrl.match(/^[^/]+@[^/:]+:(.+)$/);
	if (scpLikeMatch) {
		pathPart = scpLikeMatch[1] ?? null;
	} else {
		try {
			// Only host-bearing URLs carry an owner/repo; raw local paths (e.g. ../repo.git) do not.
			const url = new URL(trimmedRemoteUrl);
			if (url.hostname) pathPart = url.pathname;
		} catch {
			/* not a parseable remote URL — no identity */
		}
	}
	if (!pathPart) return fallbackBasename;

	const normalizedPath = pathPart
		.replace(/^\/+/, "")
		.replace(/\/+$/, "")
		.replace(/\.git$/, "");
	const segments = normalizedPath.split("/").filter(Boolean);
	if (segments.length >= 2) {
		const owner = segments[segments.length - 2];
		const repo = segments[segments.length - 1];
		if (owner !== "." && owner !== ".." && repo !== "." && repo !== "..") {
			return `${owner}/${repo}`;
		}
	}

	return fallbackBasename;
}

export interface GitInfo {
	repoName: string;
	isRepo: boolean;
	remoteUrl: string | null;
	toplevel: string | null;
	mainRoot: string | null;
	isLinkedWorktree: boolean;
}

export async function resolveGitInfo(pi: ExtensionAPI, dir: string): Promise<GitInfo> {
	const cwd = path.resolve(dir);
	try {
		const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], {
			cwd,
			timeout: 10_000,
		});
		if (result.code !== 0 || !result.stdout.trim()) {
			return {
				repoName: path.basename(cwd),
				isRepo: false,
				remoteUrl: null,
				toplevel: null,
				mainRoot: null,
				isLinkedWorktree: false,
			};
		}

		const toplevel = path.resolve(result.stdout.trim());
		let mainRoot = toplevel;
		let isLinkedWorktree = false;
		try {
			const gitDirs = await pi.exec("git", ["rev-parse", "--git-dir", "--git-common-dir"], {
				cwd,
				timeout: 10_000,
			});
			const lines = gitDirs.stdout
				.split("\n")
				.map((line) => line.trim())
				.filter(Boolean);
			const [gitDirLine, commonDirLine] = lines;
			if (gitDirs.code === 0 && gitDirLine && commonDirLine) {
				const gitDir = path.resolve(cwd, gitDirLine);
				const commonDir = path.resolve(cwd, commonDirLine);
				isLinkedWorktree = gitDir !== commonDir;
				mainRoot = isLinkedWorktree ? path.dirname(commonDir) : toplevel;
			}
		} catch {
			mainRoot = toplevel;
			isLinkedWorktree = false;
		}

		let remoteUrl: string | null = null;
		try {
			const remote = await pi.exec("git", ["-C", toplevel, "remote", "get-url", "origin"], {
				timeout: 10_000,
			});
			if (remote.code === 0 && remote.stdout.trim()) remoteUrl = remote.stdout.trim();
		} catch {
			/* no remote */
		}

		const repoName = deriveRepoIdentity(remoteUrl, path.basename(toplevel));
		return { repoName, isRepo: true, remoteUrl, toplevel, mainRoot, isLinkedWorktree };
	} catch {
		return {
			repoName: path.basename(cwd),
			isRepo: false,
			remoteUrl: null,
			toplevel: null,
			mainRoot: null,
			isLinkedWorktree: false,
		};
	}
}
