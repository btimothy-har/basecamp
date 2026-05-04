import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

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

export async function resolveGitInfo(
	pi: ExtensionAPI,
	dir: string,
): Promise<{ repoName: string; isRepo: boolean; remoteUrl: string | null; toplevel: string | null }> {
	const cwd = path.resolve(dir);
	try {
		const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], {
			cwd,
			timeout: 10_000,
		});
		if (result.code !== 0 || !result.stdout.trim()) {
			return { repoName: path.basename(cwd), isRepo: false, remoteUrl: null, toplevel: null };
		}

		const toplevel = path.resolve(result.stdout.trim());
		const repoName = path.basename(toplevel);

		let remoteUrl: string | null = null;
		try {
			const remote = await pi.exec("git", ["-C", toplevel, "remote", "get-url", "origin"], {
				timeout: 10_000,
			});
			if (remote.code === 0 && remote.stdout.trim()) remoteUrl = remote.stdout.trim();
		} catch {
			/* no remote */
		}

		return { repoName, isRepo: true, remoteUrl, toplevel };
	} catch {
		return { repoName: path.basename(cwd), isRepo: false, remoteUrl: null, toplevel: null };
	}
}
