/**
 * Session — state management and session bootstrap.
 *
 * session_start:
 *   - Reads --project / --label / --style flags
 *   - Resolves project config from ~/.basecamp/config.json
 *   - Creates/enters worktree if --label provided
 *   - Changes cwd to the effective working directory
 *   - Loads .env from the project directory
 *   - Caches session state (dirs, working style, context, worktree info)
 *   - Collects git status snapshot
 *   - Creates work directories
 *   - Sets BASECAMP_* env vars
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { type SessionState, resolveSessionState } from "../../config";
import type { GitStatus } from "../../context";
import { getOrCreateWorktree, registerWorktreeGuards } from "./worktree";

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let state: SessionState | null = null;
let gitStatus: GitStatus | null = null;

export function getGitStatus(): GitStatus | null {
	return gitStatus;
}

export function getState(): SessionState {
	return state ?? {
		projectName: null,
		project: null,
		primaryDir: process.cwd(),
		secondaryDirs: [],
		repoName: path.basename(process.cwd()),
		isRepo: false,
		remoteUrl: null,
		workDir: `/tmp/pi/${path.basename(process.cwd())}`,
		workingStyle: "engineering",
		worktreeDir: null,
		worktreeLabel: null,
		worktreeBranch: null,
		contextContent: null,
	};
}

// ---------------------------------------------------------------------------
// Git helpers
// ---------------------------------------------------------------------------

async function resolveGitInfo(
	pi: ExtensionAPI,
	dir: string,
): Promise<{ repoName: string; isRepo: boolean; remoteUrl: string | null }> {
	try {
		const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], {
			cwd: dir,
			timeout: 10_000,
		});
		const toplevel = result.stdout.trim();
		const repoName = path.basename(toplevel);

		let remoteUrl: string | null = null;
		try {
			const remote = await pi.exec("git", ["-C", toplevel, "remote", "get-url", "origin"], {
				timeout: 10_000,
			});
			if (remote.code === 0) remoteUrl = remote.stdout.trim();
		} catch { /* no remote */ }

		return { repoName, isRepo: true, remoteUrl };
	} catch {
		return { repoName: path.basename(dir), isRepo: false, remoteUrl: null };
	}
}

async function collectGitStatus(
	pi: ExtensionAPI,
	dir: string,
): Promise<GitStatus | null> {
	try {
		const branchResult = await pi.exec("git", ["branch", "--show-current"], {
			cwd: dir,
			timeout: 10_000,
		});
		const branch = branchResult.code === 0 ? branchResult.stdout.trim() : null;
		if (branch === null) return null;

		// Detect main branch
		let mainBranch = "main";
		const checkMain = await pi.exec("git", ["rev-parse", "--verify", "main"], {
			cwd: dir,
			timeout: 10_000,
		});
		if (checkMain.code !== 0) {
			const checkMaster = await pi.exec("git", ["rev-parse", "--verify", "master"], {
				cwd: dir,
				timeout: 10_000,
			});
			if (checkMaster.code === 0) mainBranch = "master";
		}

		const statusResult = await pi.exec("git", ["status", "--short"], {
			cwd: dir,
			timeout: 10_000,
		});
		const status = statusResult.code === 0 ? statusResult.stdout.trim() : "";

		const logResult = await pi.exec("git", ["log", "--oneline", "-5"], {
			cwd: dir,
			timeout: 10_000,
		});
		const recentCommits = logResult.code === 0 ? logResult.stdout.trim() : "";

		return { branch, mainBranch, status, recentCommits };
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerSession(pi: ExtensionAPI): void {
	// Register CLI flags
	pi.registerFlag("project", {
		description: "Basecamp project name (from ~/.basecamp/config.json)",
		type: "string",
	});
	pi.registerFlag("label", {
		description: "Work in a labeled git worktree (creates if new)",
		type: "string",
	});
	pi.registerFlag("style", {
		description: "Override working style (e.g. engineering, advisor)",
		type: "string",
	});
	pi.registerFlag("agent-prompt", {
		description: "Agent prompt file — replaces working style + system.md (used by worker spawner)",
		type: "string",
	});

	// Register worktree tool guards (reads state lazily)
	registerWorktreeGuards(pi, getState);

	// --- Session start: resolve everything ---
	pi.on("session_start", async (_event, ctx) => {
		const projectName = (pi.getFlag("project") as string | undefined) ?? null;
		const label = (pi.getFlag("label") as string | undefined) ?? null;
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;

		// Resolve git info from ctx.cwd (the directory pi was started in)
		const gitInfo = await resolveGitInfo(pi, ctx.cwd);

		// Build session state
		state = resolveSessionState({
			projectName,
			cwd: ctx.cwd,
			repoName: gitInfo.repoName,
			isRepo: gitInfo.isRepo,
			remoteUrl: gitInfo.remoteUrl,
			styleOverride,
		});

		// Handle worktree if --label provided
		if (label) {
			if (!projectName) {
				ctx.ui.notify("basecamp: --label requires --project", "error");
			} else if (!state.isRepo) {
				ctx.ui.notify("basecamp: --label requires a git repository", "error");
			} else {
				try {
					const wt = await getOrCreateWorktree(
						pi,
						state.primaryDir,
						state.repoName,
						label,
						projectName,
					);
					state.worktreeDir = wt.worktreeDir;
					state.worktreeLabel = label;
					state.worktreeBranch = wt.branch;
					ctx.ui.notify(
						`basecamp: worktree ${wt.created ? "created" : "attached"} → ${label}`,
						"info",
					);
				} catch (err) {
					const msg = err instanceof Error ? err.message : String(err);
					ctx.ui.notify(`basecamp: worktree failed — ${msg}`, "error");
				}
			}
		}

		// Change to the effective working directory
		const effectiveDir = state.worktreeDir ?? state.primaryDir;
		try {
			process.chdir(effectiveDir);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			ctx.ui.notify(`basecamp: chdir failed — ${msg}`, "error");
		}

		// Load .env from the project's primary directory
		const dotenvPath = path.join(state.primaryDir, ".env");
		try {
			const content = fsSync.readFileSync(dotenvPath, "utf8");
			for (const line of content.split("\n")) {
				if (line.startsWith("#") || !line.includes("=")) continue;
				const eq = line.indexOf("=");
				const key = line.slice(0, eq).trim();
				const value = line.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
				if (key && /^[A-Za-z_]\w*$/.test(key)) {
					process.env[key] = value;
				}
			}
		} catch { /* no .env file is fine */ }

		// Collect git status from the effective working dir
		if (state.isRepo) {
			gitStatus = await collectGitStatus(pi, effectiveDir);
		} else {
			gitStatus = null;
		}

		// Create work directories
		await fs.mkdir(path.join(state.workDir, "pull-requests"), { recursive: true });

		// Set env vars for downstream tools (observer, workers, etc.)
		process.env.BASECAMP_PROJECT = state.projectName ?? "";
		process.env.BASECAMP_REPO = state.repoName;
		process.env.BASECAMP_WORK_DIR = state.workDir;

		// Notify
		const parts = [`repo=${state.repoName}`];
		if (state.projectName) parts.push(`project=${state.projectName}`);
		if (state.worktreeLabel) parts.push(`worktree=${state.worktreeLabel}`);
		ctx.ui.notify(`basecamp: ${parts.join(", ")}`, "info");
	});
}
