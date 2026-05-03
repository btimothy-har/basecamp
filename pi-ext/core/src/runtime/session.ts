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
import {
	type BasecampProjectState,
	getSessionEffectiveCwd,
	resolveSessionState,
	type SessionState,
} from "../../../platform/config";
import {
	getBasecampProjectState,
	requireBasecampProjectState,
	resetBasecampProjectRuntime,
	setBasecampProjectState,
} from "../../../platform/project";
import { getSessionState, requireSessionState, resetSessionRuntime, setSessionState } from "../../../platform/session";
import {
	attachWorkspaceWorktreePath,
	getWorkspaceService,
	registerWorkspaceAllowedRootsProvider,
	requireWorkspaceState,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "../../../platform/workspace";
import {
	appendWorkspaceAffinity,
	latestWorkspaceAffinity,
	repoMatchesWorkspaceAffinity,
} from "../../../workspace/src/affinity.ts";
import { registerWorkspaceRuntime } from "../../../workspace/src/service.ts";
import { type WorktreeResult } from "../../../workspace/src/worktree.ts";
import { resetAgentMode } from "./mode";

export function getEffectiveCwd(): string {
	const workspace = getWorkspaceService();
	if (workspace?.current()) return workspace.getEffectiveCwd();
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

function sessionStateToProjectState(s: SessionState): BasecampProjectState {
	return {
		projectName: s.projectName,
		project: s.project,
		additionalDirs: s.additionalDirs,
		workingStyle: s.workingStyle,
		contextContent: s.contextContent,
		projectWarnings: s.projectWarnings,
	};
}

interface WorktreeApplyOptions {
	persistAffinity?: boolean;
}

function worktreeResultToWorkspaceWorktree(wt: WorktreeResult): WorkspaceWorktree {
	return {
		kind: "git-worktree",
		label: wt.label,
		path: wt.worktreeDir,
		branch: wt.branch,
		created: wt.created,
	};
}

async function applyWorktree(pi: ExtensionAPI, wt: WorktreeResult, options: WorktreeApplyOptions = {}): Promise<void> {
	const s = requireSessionState();
	s.worktreeDir = wt.worktreeDir;
	s.worktreeLabel = wt.label;
	s.worktreeBranch = wt.branch;

	setBasecampEnv(s);
	if (options.persistAffinity ?? true) {
		const workspaceState = requireWorkspaceState();
		const target =
			workspaceState.activeWorktree?.path === wt.worktreeDir
				? workspaceState.activeWorktree
				: worktreeResultToWorkspaceWorktree(wt);
		appendWorkspaceAffinity(pi, workspaceState, target);
	}
}

function workspaceWorktreeToWorktree(target: WorkspaceWorktree): WorktreeResult {
	return {
		worktreeDir: target.path,
		label: target.label,
		branch: target.branch ?? "detached",
		created: target.created,
	};
}

async function attachWorktree(
	pi: ExtensionAPI,
	worktreeDir: string,
	options: WorktreeApplyOptions = {},
): Promise<WorktreeResult> {
	const s = requireSessionState();
	if (!s.isRepo) throw new Error("Worktree attachment requires a git repository");
	const target = await attachWorkspaceWorktreePath(worktreeDir);
	const wt = workspaceWorktreeToWorktree(target);
	await applyWorktree(pi, wt, options);
	return wt;
}

const WORKTREE_AFFINITY_RESTORE_REASONS = new Set<SessionStartEvent["reason"]>(["resume", "reload", "fork"]);

function setSessionStateFromWorkspace(workspaceState: WorkspaceState, styleOverride: string | undefined): void {
	const repoRoot = workspaceState.repo?.root ?? workspaceState.launchCwd;
	const sessionState = resolveSessionState({
		launchCwd: workspaceState.launchCwd,
		repoRoot,
		repoName: workspaceState.repo?.name ?? path.basename(repoRoot),
		isRepo: workspaceState.repo?.isRepo ?? false,
		remoteUrl: workspaceState.repo?.remoteUrl ?? null,
		scratchDir: workspaceState.scratchDir,
		styleOverride,
	});
	sessionState.unsafeEdit = workspaceState.unsafeEdit;
	setSessionState(sessionState);
	setBasecampProjectState(sessionStateToProjectState(sessionState));
}

interface LegacySessionSyncGlobal {
	registered: boolean;
}

const legacySessionSyncKey = Symbol.for("basecamp.workspace.legacy-session-sync");

type GlobalWithLegacySessionSync = typeof globalThis & {
	[legacySessionSyncKey]?: LegacySessionSyncGlobal;
};

function syncLegacySessionStateFromWorkspace(workspaceState: WorkspaceState | null): void {
	if (!workspaceState) return;

	const sessionState = getSessionState();
	if (!sessionState) return;

	sessionState.scratchDir = workspaceState.scratchDir;
	sessionState.unsafeEdit = workspaceState.unsafeEdit;
	sessionState.worktreeDir = workspaceState.activeWorktree?.path ?? null;
	sessionState.worktreeLabel = workspaceState.activeWorktree?.label ?? null;
	sessionState.worktreeBranch = workspaceState.activeWorktree?.branch ?? null;
	setBasecampEnv(sessionState);
}

function registerLegacySessionStateSync(workspace: ReturnType<typeof registerWorkspaceRuntime>): void {
	const globalObject = globalThis as GlobalWithLegacySessionSync;
	globalObject[legacySessionSyncKey] ??= { registered: false };
	const sync = globalObject[legacySessionSyncKey];
	if (sync.registered) return;

	workspace.onChange(syncLegacySessionStateFromWorkspace);
	sync.registered = true;
}

async function restoreWorktreeAffinity(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const workspaceState = requireWorkspaceState();
	if (!workspaceState.repo) return;

	const affinity = latestWorkspaceAffinity(ctx.sessionManager.getBranch());
	if (!affinity || !repoMatchesWorkspaceAffinity(workspaceState, affinity)) return;

	try {
		const wt = await attachWorktree(pi, affinity.worktree.path, { persistAffinity: false });
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
	const workspace = registerWorkspaceRuntime(pi);
	registerLegacySessionStateSync(workspace);

	// Register CLI flags
	pi.registerFlag("worktree-dir", {
		description: "Attach to an existing workspace worktree directory",
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

	registerWorkspaceAllowedRootsProvider({
		id: "basecamp-project",
		roots: () => getBasecampProjectState()?.additionalDirs ?? [],
	});

	// --- Session start: resolve everything ---
	pi.on("session_start", async (event, ctx) => {
		resetAgentMode();
		resetSessionRuntime();
		resetBasecampProjectRuntime();

		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const launchCwd = path.resolve(ctx.cwd);

		const { state: workspaceState, unsafeEditResult } = await workspace.initialize({
			launchCwd,
			unsafeEditFlag: pi.getFlag("unsafe-edit") === true,
			unsafeEditConstraints: {
				readOnly: pi.getFlag("read-only") === true,
				hasUI: ctx.hasUI,
				isSubagent: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0,
			},
		});

		// Build legacy session state from workspace runtime state for compatibility.
		setSessionStateFromWorkspace(workspaceState, styleOverride);

		for (const warning of requireBasecampProjectState().projectWarnings) {
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
