/**
 * git_status tool — current repository state for the Basecamp working directory.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { exec } from "../../platform/exec.ts";
import { getWorkspaceState, type WorkspaceState } from "../../platform/workspace.ts";

interface GitCommandResult {
	code: number;
	stdout: string;
}

const StatusParams = Type.Object({});

export interface WorktreeInfo {
	label: string;
	path: string;
	branch: string;
}

export interface GitStatusDetails {
	repoName: string;
	repoRoot: string;
	effectiveRoot: string;
	worktree: WorktreeInfo | null;
	branch: string;
	defaultBranch: string;
	upstream: string;
	workingTreeStatus: string[];
	recentCommits: string[];
}

async function git(pi: ExtensionAPI, args: string[]): Promise<GitCommandResult> {
	const result = await exec(pi, "git", args, { timeout: 10_000 });
	return {
		code: result.code,
		stdout: result.stdout.trimEnd(),
	};
}

async function detectDefaultBranch(pi: ExtensionAPI): Promise<string> {
	const originHead = await git(pi, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]);
	if (originHead.code === 0 && originHead.stdout.startsWith("origin/")) {
		return originHead.stdout.slice("origin/".length);
	}

	for (const candidate of ["main", "master"]) {
		const check = await git(pi, ["rev-parse", "--verify", candidate]);
		if (check.code === 0) return candidate;
	}

	return "unknown";
}

async function currentBranch(pi: ExtensionAPI): Promise<string> {
	const branch = await git(pi, ["branch", "--show-current"]);
	if (branch.code === 0 && branch.stdout) return branch.stdout;

	const head = await git(pi, ["rev-parse", "--short", "HEAD"]);
	return head.code === 0 && head.stdout ? `detached HEAD (${head.stdout})` : "unknown";
}

function parseAheadBehind(output: string): { ahead: number; behind: number } {
	// left-right count for @{u}...HEAD reports upstream first, then HEAD.
	const [behindRaw, aheadRaw] = output.split(/\s+/);
	const ahead = Number(aheadRaw ?? 0);
	const behind = Number(behindRaw ?? 0);
	return {
		ahead: Number.isFinite(ahead) ? ahead : 0,
		behind: Number.isFinite(behind) ? behind : 0,
	};
}

async function upstreamSummary(pi: ExtensionAPI): Promise<string> {
	const upstream = await git(pi, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]);
	if (upstream.code !== 0 || !upstream.stdout) return "none";

	const counts = await git(pi, ["rev-list", "--left-right", "--count", "@{u}...HEAD"]);
	if (counts.code !== 0 || !counts.stdout) return upstream.stdout;

	const { ahead, behind } = parseAheadBehind(counts.stdout);
	return `${upstream.stdout} (ahead ${ahead}, behind ${behind})`;
}

function formatOutput(workspace: WorkspaceState | null, details: GitStatusDetails): string[] {
	const lines: string[] = [];

	if (details.worktree) {
		lines.push(
			`Repository: ${details.repoName}`,
			`Protected checkout: ${details.repoRoot}`,
			"",
			`Active worktree: ${details.worktree.label} (branch: ${details.worktree.branch})`,
			`Worktree root: ${details.worktree.path}`,
			"Git status source: active worktree",
		);
		if (path.resolve(details.effectiveRoot) !== path.resolve(details.worktree.path)) {
			lines.push(`Git status root: ${details.effectiveRoot}`);
		}
	} else if (workspace?.repo) {
		lines.push(`Repository: ${details.repoName}`, `Repository root: ${details.repoRoot}`);
	} else {
		lines.push(`Git root: ${details.effectiveRoot}`);
	}

	lines.push(
		"",
		`Branch: ${details.branch}`,
		`Default branch: ${details.defaultBranch}`,
		`Upstream: ${details.upstream}`,
	);

	if (details.workingTreeStatus.length > 0) {
		lines.push("", "Working tree:", ...details.workingTreeStatus);
	} else {
		lines.push("", "Working tree: clean");
	}

	lines.push("", "Recent commits:", ...(details.recentCommits.length > 0 ? details.recentCommits : ["none"]));

	return lines;
}

export function registerStatusTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "git_status",
		label: "Git Status",
		description:
			"Get current repository state for the Basecamp working directory; call before staging, committing, pushing, or PR work.",
		parameters: StatusParams,
		async execute() {
			const effectiveRootResult = await git(pi, ["rev-parse", "--show-toplevel"]);
			if (effectiveRootResult.code !== 0 || !effectiveRootResult.stdout) {
				return {
					isError: true,
					details: null,
					content: [{ type: "text", text: "Current working directory is not a git repository." }],
				};
			}

			const effectiveRoot = effectiveRootResult.stdout;
			const workspace = getWorkspaceState();

			const [branch, defaultBranch, upstream, statusResult, recentCommitsResult] = await Promise.all([
				currentBranch(pi),
				detectDefaultBranch(pi),
				upstreamSummary(pi),
				git(pi, ["status", "--short"]),
				git(pi, ["log", "--oneline", "-5"]),
			]);

			const workingTreeStatus =
				statusResult.code === 0 && statusResult.stdout
					? statusResult.stdout.split("\n").filter((line) => line.trim())
					: [];
			const recentCommits =
				recentCommitsResult.code === 0 && recentCommitsResult.stdout
					? recentCommitsResult.stdout.split("\n").filter((line) => line.trim())
					: [];

			const worktree: WorktreeInfo | null = workspace?.activeWorktree
				? {
						label: workspace.activeWorktree.label,
						path: workspace.activeWorktree.path,
						branch: workspace.activeWorktree.branch ?? branch,
					}
				: null;

			const repoName = workspace?.repo?.name ?? (path.basename(effectiveRoot) || "unknown");
			const repoRoot = workspace?.protectedRoot ?? workspace?.repo?.root ?? effectiveRoot;

			const details: GitStatusDetails = {
				repoName,
				repoRoot,
				effectiveRoot,
				worktree,
				branch,
				defaultBranch,
				upstream,
				workingTreeStatus,
				recentCommits,
			};

			const lines = formatOutput(workspace, details);

			return {
				details,
				content: [{ type: "text", text: lines.join("\n") }],
			};
		},
	});
}
