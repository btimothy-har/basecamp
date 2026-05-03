/**
 * Session — state management and session bootstrap.
 *
 * session_start:
 *   - Reads --worktree-dir / --style flags
 *   - Detects the configured project from Pi's launch cwd git repo root
 *   - Attaches to an existing worktree if --worktree-dir provided
 *   - Loads .env from the repository root
 *   - Caches session state (repo root, launch cwd, working style, context, worktree info)
 *   - Creates work directories
 *   - Sets BASECAMP_* env vars
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import { getSessionEffectiveCwd, resolveSessionState, type SessionState } from "../../../platform/config";
import { registerCwdProvider } from "../../../platform/exec";
import { getSessionState, requireSessionState, resetSessionRuntime, setSessionState } from "../../../platform/session";
import { resolveGitInfo } from "../../../workspace/src/repo";
import { resetAgentMode } from "./mode";
import { applyUnsafeEditFlag } from "./unsafe-edit.ts";
import { attachWorktreeDir, getOrCreateWorktree, registerWorktreeGuards, type WorktreeResult } from "./worktree";
import { appendWorktreeAffinity, latestWorktreeAffinity, repoMatchesAffinity } from "./worktree-affinity";

export function getEffectiveCwd(): string {
	return getSessionEffectiveCwd(getState());
}

export function getState(): SessionState {
	const cwd = process.cwd();
	return (
		getSessionState() ?? {
			projectName: null,
			project: null,
			launchCwd: cwd,
			repoRoot: cwd,
			additionalDirs: [],
			repoName: path.basename(cwd),
			isRepo: false,
			remoteUrl: null,
			scratchDir: `/tmp/pi/${path.basename(cwd)}`,
			workingStyle: "engineering",
			worktreeDir: null,
			worktreeLabel: null,
			worktreeBranch: null,
			contextContent: null,
			projectWarnings: [],
			unsafeEdit: false,
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

	setBasecampEnv(s);
	if (options.persistAffinity ?? true) appendWorktreeAffinity(pi, s, wt);
}

export async function activateWorktree(pi: ExtensionAPI, label: string): Promise<WorktreeResult> {
	const s = requireSessionState();
	if (!s.isRepo) throw new Error("Worktree activation requires a git repository");
	const wt = await getOrCreateWorktree(pi, s.repoRoot, s.repoName, label);
	await applyWorktree(pi, wt);
	return wt;
}

export async function attachWorktree(pi: ExtensionAPI, worktreeDir: string): Promise<WorktreeResult> {
	const s = requireSessionState();
	if (!s.isRepo) throw new Error("Worktree attachment requires a git repository");
	const wt = await attachWorktreeDir(pi, s.repoRoot, s.repoName, worktreeDir);
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
		const wt = await attachWorktreeDir(pi, state.repoRoot, state.repoName, affinity.worktreeDir);
		await applyWorktree(pi, wt, { persistAffinity: false });
		ctx.ui.notify(`basecamp: restored worktree → ${wt.label}`, "info");
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.ui.notify(`basecamp: saved worktree restore skipped — ${msg}`, "warning");
	}
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export function registerSession(pi: ExtensionAPI): void {
	registerCwdProvider(getEffectiveCwd);

	// Register CLI flags
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
	pi.registerFlag("unsafe-edit", {
		description: "Allow edit/write to target protected checkout directly (safe_git protections still apply)",
		type: "boolean",
	});

	// Register worktree tool guards (reads state lazily)
	registerWorktreeGuards(pi, getState);

	// --- Session start: resolve everything ---
	pi.on("session_start", async (event, ctx) => {
		resetAgentMode();
		resetSessionRuntime();

		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const launchCwd = path.resolve(ctx.cwd);

		// Resolve git info from ctx.cwd (the directory pi was launched in)
		const gitInfo = await resolveGitInfo(pi, launchCwd);

		// Build session state
		setSessionState(
			resolveSessionState({
				launchCwd,
				repoRoot: gitInfo.toplevel ?? launchCwd,
				repoName: gitInfo.repoName,
				isRepo: gitInfo.isRepo,
				remoteUrl: gitInfo.remoteUrl,
				styleOverride,
			}),
		);

		for (const warning of requireSessionState().projectWarnings) {
			ctx.ui.notify(`basecamp: ${warning}`, "warning");
		}

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

		const unsafeEditResult = applyUnsafeEditFlag(state, pi.getFlag("unsafe-edit") === true, {
			readOnly: pi.getFlag("read-only") === true,
			hasUI: ctx.hasUI,
			isSubagent: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0,
		});
		if (unsafeEditResult === "ignored-read-only") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored because --read-only is active", "warning");
		} else if (unsafeEditResult === "ignored-subagent") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored in subagent sessions", "warning");
		} else if (unsafeEditResult === "ignored-non-interactive") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored without interactive UI", "warning");
		}

		// Load .env from the repository root
		const dotenvPath = path.join(state.repoRoot, ".env");
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
