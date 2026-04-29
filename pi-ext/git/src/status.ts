/**
 * git_status tool — current repository state for the Basecamp working directory.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { exec } from "../../platform/exec";

interface GitCommandResult {
	code: number;
	stdout: string;
}

const StatusParams = Type.Object({});

async function git(pi: ExtensionAPI, args: string[]): Promise<GitCommandResult> {
	const result = await exec(pi, "git", args, { timeout: 10_000 });
	return {
		code: result.code,
		stdout: result.stdout.trim(),
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

export function registerStatusTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "git_status",
		label: "Git Status",
		description:
			"Get current repository state for the Basecamp working directory; call before staging, committing, pushing, or PR work.",
		parameters: StatusParams,
		async execute() {
			const root = await git(pi, ["rev-parse", "--show-toplevel"]);
			if (root.code !== 0 || !root.stdout) {
				return {
					isError: true,
					details: null,
					content: [{ type: "text", text: "Current working directory is not a git repository." }],
				};
			}

			const [branch, defaultBranch, upstream, status, recentCommits] = await Promise.all([
				currentBranch(pi),
				detectDefaultBranch(pi),
				upstreamSummary(pi),
				git(pi, ["status", "--short"]),
				git(pi, ["log", "--oneline", "-5"]),
			]);

			const lines = [
				`Repository root: ${root.stdout}`,
				`Branch: ${branch}`,
				`Default branch: ${defaultBranch}`,
				`Upstream: ${upstream}`,
			];

			if (status.code === 0 && status.stdout) {
				lines.push("", "Working tree:", status.stdout);
			} else {
				lines.push("", "Working tree: clean");
			}

			lines.push(
				"",
				"Recent commits:",
				recentCommits.code === 0 && recentCommits.stdout ? recentCommits.stdout : "none",
			);

			return {
				details: null,
				content: [{ type: "text", text: lines.join("\n") }],
			};
		},
	});
}
