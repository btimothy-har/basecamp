/**
 * Session — state management and session bootstrap.
 *
 * session_start:
 *   - Reads --project / --worktree-dir / --style flags
 *   - Resolves project config from ~/.pi/basecamp/config.json
 *   - Attaches to an existing worktree if --worktree-dir provided
 *   - Changes cwd to the effective working directory
 *   - Loads .env from the project directory
 *   - Caches session state (dirs, working style, context, worktree info)
 *   - Collects git status snapshot
 *   - Creates work directories
 *   - Sets BASECAMP_* env vars
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import { resolveSessionState, type SessionState } from "../../../platform/config";
import type { GitStatus } from "../../../platform/context";
import { registerCwdProvider } from "../../../platform/exec";
import {
	getSessionGitStatus,
	getSessionState,
	requireSessionState,
	resetSessionRuntime,
	setSessionGitStatus,
	setSessionState,
} from "../../../platform/session";
import { resetAgentMode } from "./mode";
import { attachWorktreeDir, getOrCreateWorktree, registerWorktreeGuards, type WorktreeResult } from "./worktree";
import { appendWorktreeAffinity, latestWorktreeAffinity, repoMatchesAffinity } from "./worktree-affinity";

export function getGitStatus(): GitStatus | null {
	return getSessionGitStatus();
}

export function getEffectiveCwd(): string {
	const s = getState();
	return s.worktreeDir ?? s.primaryDir;
}

export function getState(): SessionState {
	return (
		getSessionState() ?? {
			projectName: null,
			project: null,
			primaryDir: process.cwd(),
			secondaryDirs: [],
			repoName: path.basename(process.cwd()),
			isRepo: false,
			remoteUrl: null,
			scratchDir: `/tmp/pi/${path.basename(process.cwd())}`,
			workingStyle: "engineering",
			worktreeDir: null,
			worktreeLabel: null,
			worktreeBranch: null,
			contextContent: null,
		}
	);
}

function setBasecampEnv(s: SessionState): void {
	process.env.BASECAMP_PROJECT = s.projectName ?? "";
	process.env.BASECAMP_REPO = s.repoName;
	process.env.BASECAMP_SCRATCH_DIR = s.scratchDir;
	process.env.BASECAMP_WORKTREE_DIR = s.worktreeDir ?? "";
	process.env.BASECAMP_WORKTREE_LABEL = s.worktreeLabel ?? "";
}

interface WorktreeApplyOptions {
	persistAffinity?: boolean;
}

async function applyWorktree(pi: ExtensionAPI, wt: WorktreeResult, options: WorktreeApplyOptions = {}): Promise<void> {
	const s = requireSessionState();
	s.worktreeDir = wt.worktreeDir;
	s.worktreeLabel = wt.label;
	s.worktreeBranch = wt.branch;

	process.chdir(getEffectiveCwd());
	setSessionGitStatus(s.isRepo ? await collectGitStatus(pi, getEffectiveCwd()) : null);
	setBasecampEnv(s);
	if (options.persistAffinity ?? true) appendWorktreeAffinity(pi, s, wt);
}

export async function activateWorktree(pi: ExtensionAPI, label: string): Promise<WorktreeResult> {
	const s = requireSessionState();
	if (!s.isRepo) throw new Error("Worktree activation requires a git repository");
	const wt = await getOrCreateWorktree(pi, s.primaryDir, s.repoName, label);
	await applyWorktree(pi, wt);
	return wt;
}

export async function attachWorktree(pi: ExtensionAPI, worktreeDir: string): Promise<WorktreeResult> {
	const s = requireSessionState();
	if (!s.isRepo) throw new Error("Worktree attachment requires a git repository");
	const wt = await attachWorktreeDir(pi, s.primaryDir, s.repoName, worktreeDir);
	await applyWorktree(pi, wt);
	return wt;
}

const WORKTREE_AFFINITY_RESTORE_REASONS = new Set<SessionStartEvent["reason"]>(["resume", "reload", "fork"]);

async function restoreWorktreeAffinity(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const state = requireSessionState();
	if (!state.isRepo) return;

	const affinity = latestWorktreeAffinity(ctx.sessionManager.getBranch());
	if (!affinity || !repoMatchesAffinity(state, affinity)) return;

	try {
		const wt = await attachWorktreeDir(pi, state.primaryDir, state.repoName, affinity.worktreeDir);
		await applyWorktree(pi, wt, { persistAffinity: false });
		ctx.ui.notify(`basecamp: restored worktree → ${wt.label}`, "info");
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.ui.notify(`basecamp: saved worktree restore skipped — ${msg}`, "warning");
	}
}

// ---------------------------------------------------------------------------
// Git helpers
// ---------------------------------------------------------------------------

async function resolveGitInfo(
	pi: ExtensionAPI,
	dir: string,
): Promise<{ repoName: string; isRepo: boolean; remoteUrl: string | null; toplevel: string | null }> {
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
		} catch {
			/* no remote */
		}

		return { repoName, isRepo: true, remoteUrl, toplevel };
	} catch {
		return { repoName: path.basename(dir), isRepo: false, remoteUrl: null, toplevel: null };
	}
}

async function collectGitStatus(pi: ExtensionAPI, dir: string): Promise<GitStatus | null> {
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
	registerCwdProvider(getEffectiveCwd);

	// Register CLI flags
	pi.registerFlag("project", {
		description: "Basecamp project name (from ~/.pi/basecamp/config.json)",
		type: "string",
	});
	pi.registerFlag("worktree-dir", {
		description: "Attach to an existing Basecamp worktree directory",
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
	pi.registerFlag("read-only", {
		description: "Prepend read-only operating constraints to the system prompt",
		type: "boolean",
	});

	// Register worktree tool guards (reads state lazily)
	registerWorktreeGuards(pi, getState);

	// --- Session start: resolve everything ---
	pi.on("session_start", async (event, ctx) => {
		resetAgentMode();
		resetSessionRuntime();

		const projectName = (pi.getFlag("project") as string | undefined) ?? null;
		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;

		// Resolve git info from ctx.cwd (the directory pi was started in)
		const gitInfo = await resolveGitInfo(pi, ctx.cwd);

		// Build session state
		setSessionState(
			resolveSessionState({
				projectName,
				cwd: gitInfo.toplevel ?? ctx.cwd,
				repoName: gitInfo.repoName,
				isRepo: gitInfo.isRepo,
				remoteUrl: gitInfo.remoteUrl,
				styleOverride,
			}),
		);

		if (worktreeDir) {
			try {
				const wt = await attachWorktree(pi, worktreeDir);
				ctx.ui.notify(`basecamp: worktree attached → ${wt.label}`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`basecamp: worktree attach failed — ${msg}`, "error");
			}
		} else if (WORKTREE_AFFINITY_RESTORE_REASONS.has(event.reason)) {
			await restoreWorktreeAffinity(pi, ctx);
		}
		const state = requireSessionState();

		try {
			process.chdir(getEffectiveCwd());
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
				const value = line
					.slice(eq + 1)
					.trim()
					.replace(/^["']|["']$/g, "");
				if (key && /^[A-Za-z_]\w*$/.test(key)) {
					process.env[key] = value;
				}
			}
		} catch {
			/* no .env file is fine */
		}

		// Collect git status from the effective working dir
		setSessionGitStatus(state.isRepo ? await collectGitStatus(pi, getEffectiveCwd()) : null);

		// Create work directories
		await fs.mkdir(path.join(state.scratchDir, "pull-requests"), { recursive: true });

		// Set env vars for downstream tools (observer, subagents, etc.)
		setBasecampEnv(state);

		// Notify
		const parts = [`repo=${state.repoName}`];
		if (state.projectName) parts.push(`project=${state.projectName}`);
		if (state.worktreeLabel) parts.push(`worktree=${state.worktreeLabel}`);
		ctx.ui.notify(`basecamp: ${parts.join(", ")}`, "info");
	});
}
