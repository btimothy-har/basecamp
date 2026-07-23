/**
 * Workspace session bootstrap — generic runtime flags and session state.
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { reapOwnedSessionWorktree } from "../../git/worktrees/lease.ts";
import { migrateLegacyWorktrees } from "../../git/worktrees/migrate.ts";
import { sweepSessionWorktrees } from "../../git/worktrees/session-sweep.ts";
import { sweepAgentWorktrees } from "../../git/worktrees/sweep.ts";
import { readLogseqGraphDir, readWorktreeSetupCommand } from "../../host/config.ts";
import { getAgentDepth, getBasecampEnv } from "../../host/env.ts";
import { getCurrentSessionState } from "../../session/state/index.ts";
import { workspaceMatchesActiveWorktreeState } from "./affinity.ts";
import { requireWorkspaceRuntime } from "./runtime.ts";
import { runWorktreeSetup, shouldRunWorktreeSetup } from "./setup.ts";
import {
	attachWorkspaceWorktreePath,
	getWorkspaceState,
	initializeWorkspace,
	registerWorkspaceAllowedRootsProvider,
	requireWorkspaceState,
	type UnsafeEditFlagResult,
	type WorkspaceWorktree,
} from "./state.ts";

async function attachWorktree(worktreeDir: string): Promise<WorkspaceWorktree> {
	return attachWorkspaceWorktreePath(worktreeDir);
}

const WORKTREE_STATE_RESTORE_REASONS = new Set<SessionStartEvent["reason"]>(["resume", "reload", "fork"]);

async function restoreActiveWorktreeState(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const workspaceState = requireWorkspaceState();
	if (!workspaceState.repo) return;

	// Core registers first in extension.ts, so its session_start already
	// initialized state for this event.
	const activeWorktree = getCurrentSessionState().activeWorktree;
	if (!activeWorktree || !workspaceMatchesActiveWorktreeState(workspaceState, activeWorktree)) return;
	// Init already recognized this linked worktree (and leased it); nothing to restore.
	if (
		workspaceState.activeWorktree &&
		path.resolve(workspaceState.activeWorktree.path) === path.resolve(activeWorktree.worktree.path)
	) {
		return;
	}

	const saved = activeWorktree.worktree;
	try {
		// Adopt-or-rebuild: activateWorktree reuses the worktree if it still exists, or rebuilds it
		// from the surviving branch if a prior exit reaped it, and (re)leases it either way. A rebuild
		// re-pays the setup hook to reprovision the environment.
		const wt = await requireWorkspaceRuntime().activateWorktree(saved.label, saved.branch ?? undefined);
		if (wt.created) {
			await runRebuiltWorktreeSetup(pi, ctx, workspaceState.repo.name, workspaceState.repo.root, wt);
			ctx.ui.notify(`basecamp: rebuilt worktree → ${wt.label}`, "info");
		} else {
			ctx.ui.notify(`basecamp: restored worktree → ${wt.label}`, "info");
		}
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.ui.notify(`basecamp: saved worktree restore skipped — ${msg}`, "warning");
	}
}

/** Re-run the per-repo setup hook after resume rebuilt a reaped worktree from its branch. */
async function runRebuiltWorktreeSetup(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	repoName: string,
	repoRoot: string,
	wt: WorkspaceWorktree,
): Promise<void> {
	const setupCommand = readWorktreeSetupCommand(repoName);
	if (!shouldRunWorktreeSetup(wt.created, setupCommand)) return;
	ctx.ui.notify("basecamp: rebuilding worktree — running setup (up to 3 min)…", "info");
	try {
		const result = await runWorktreeSetup(pi, { command: setupCommand as string, worktreeDir: wt.path, repoRoot });
		if (result.timedOut) {
			ctx.ui.notify("basecamp: worktree setup timed out — continuing.", "warning");
		} else if (result.exitCode !== 0) {
			ctx.ui.notify(`basecamp: worktree setup exited ${result.exitCode} — continuing.`, "warning");
		}
	} catch (err) {
		ctx.ui.notify(
			`basecamp: worktree setup error — continuing: ${err instanceof Error ? err.message : String(err)}`,
			"warning",
		);
	}
}

function notifyUnsafeEditResult(ctx: ExtensionContext, result: UnsafeEditFlagResult): void {
	if (result === "ignored-read-only") {
		ctx.ui.notify("basecamp: --unsafe-edit ignored because --read-only is active", "warning");
	} else if (result === "ignored-subagent") {
		ctx.ui.notify("basecamp: --unsafe-edit ignored in subagent sessions", "warning");
	} else if (result === "ignored-non-interactive") {
		ctx.ui.notify("basecamp: --unsafe-edit ignored without interactive UI", "warning");
	}
}

async function migrateLegacyWorktreesForSession(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	launchCwd: string,
	isSubagent: boolean,
): Promise<void> {
	if (isSubagent) return;

	try {
		const state = requireWorkspaceState();
		if (!state.repo) return;

		const result = await migrateLegacyWorktrees(pi, {
			repoRoot: state.repo.root,
			identity: state.repo.name,
			cwd: launchCwd,
		});
		if (result.moved.length > 0) {
			ctx.ui.notify(`basecamp: migrated ${result.moved.length} legacy worktree(s) → ${state.repo.name}`, "info");
		}
		if (result.skipped.length > 0) {
			ctx.ui.notify(
				`basecamp: ${result.skipped.length} legacy worktree(s) not migrated (${result.skipped.map((skip) => skip.label).join(", ")})`,
				"warning",
			);
		}
	} catch {
		/* migration is best-effort and must not interrupt session start */
	}
}

async function sweepAgentWorktreesForSession(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	isSubagent: boolean,
): Promise<void> {
	if (isSubagent) return;

	try {
		const state = requireWorkspaceState();
		if (!state.repo) return;

		const result = await sweepAgentWorktrees(pi, state.repo.root, state.repo.name);
		if (result.removed.length > 0) {
			ctx.ui.notify(`basecamp: reclaimed ${result.removed.length} merged agent worktree(s)`, "info");
		}
	} catch {
		/* sweep is best-effort and must not interrupt session start */
	}
}

async function sweepSessionWorktreesForSession(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	isSubagent: boolean,
): Promise<void> {
	if (isSubagent) return;

	try {
		const state = requireWorkspaceState();
		if (!state.repo) return;

		const result = await sweepSessionWorktrees(pi, state.repo.root, state.repo.name);
		if (result.reclaimed.length > 0) {
			ctx.ui.notify(`basecamp: reclaimed ${result.reclaimed.length} cold worktree(s)`, "info");
		}
		if (result.surfaced.length > 0) {
			ctx.ui.notify(`basecamp: ${result.surfaced.length} dirty worktree(s) reclaimable — /worktree prune`, "info");
		}
	} catch {
		/* sweep is best-effort and must not interrupt session start */
	}
}

function loadDotenv(root: string): void {
	const dotenvPath = path.join(root, ".env");
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
}

export function registerLogseqAllowedRootProvider(homeDir?: string): void {
	registerWorkspaceAllowedRootsProvider({
		id: "logseq",
		roots: () => {
			const dir = readLogseqGraphDir(homeDir);
			return dir ? [dir] : [];
		},
	});
}

export function registerWorkspaceSession(pi: ExtensionAPI): void {
	requireWorkspaceRuntime();
	registerLogseqAllowedRootProvider();

	pi.registerFlag("worktree-dir", {
		description: "Attach to an existing workspace worktree directory",
		type: "string",
	});
	pi.registerFlag("read-only", {
		description: "Prepend read-only operating constraints to the system prompt",
		type: "boolean",
	});
	pi.registerFlag("unsafe-edit", {
		description: "Allow edit/write to target protected checkout directly (bash reviewer protections still apply)",
		type: "boolean",
	});
	pi.registerFlag("unsafe-edit-sandboxed", {
		description: "Permit --unsafe-edit in an externally sandboxed non-interactive or subagent session",
		type: "boolean",
	});

	pi.on("session_start", async (event, ctx) => {
		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const launchCwd = path.resolve(ctx.cwd);
		const isSubagent = getAgentDepth() > 0;
		// Only top-level sessions lease their worktree; subagents keep their daemon-owned agent lock.
		const sessionId = isSubagent ? null : ctx.sessionManager.getSessionId();

		const { unsafeEditResult } = await initializeWorkspace({
			launchCwd,
			sessionId,
			unsafeEditFlag: pi.getFlag("unsafe-edit") === true,
			unsafeEditConstraints: {
				readOnly: pi.getFlag("read-only") === true,
				hasUI: ctx.hasUI,
				isSubagent,
				sandboxed: pi.getFlag("unsafe-edit-sandboxed") === true && getBasecampEnv("BASECAMP_EXTERNAL_SANDBOX") === "1",
			},
		});

		await migrateLegacyWorktreesForSession(pi, ctx, launchCwd, isSubagent);
		await sweepAgentWorktreesForSession(pi, ctx, isSubagent);
		await sweepSessionWorktreesForSession(pi, ctx, isSubagent);

		if (worktreeDir) {
			try {
				const wt = await attachWorktree(worktreeDir);
				ctx.ui.notify(`basecamp: worktree attached → ${wt.label}`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`basecamp: worktree attach failed — ${msg}`, "error");
			}
		} else if (!isSubagent && WORKTREE_STATE_RESTORE_REASONS.has(event.reason)) {
			// Worktree-state restore is a human convenience for reopened sessions. Daemon-spawned
			// runs are born inside their own workspace — a forked ask answerer would otherwise
			// inherit and re-attach the ask target's live worktree.
			await restoreActiveWorktreeState(pi, ctx);
		}

		notifyUnsafeEditResult(ctx, unsafeEditResult);

		const latestWorkspaceState = requireWorkspaceState();
		loadDotenv(latestWorkspaceState.repo?.root ?? latestWorkspaceState.launchCwd);
		await fs.mkdir(path.join(latestWorkspaceState.scratchDir, "pull-requests"), { recursive: true });
	});

	pi.on("session_shutdown", async (event, ctx) => {
		// Primary session teardown: a top-level session at genuine exit reaps its own worktree.
		// Subagents are daemon-owned; reload/new/resume/fork are transitions, not exits. The cold
		// backstop sweep covers a crash that never fires this handler.
		if (getAgentDepth() > 0 || event.reason !== "quit") return;
		const state = getWorkspaceState();
		if (!state?.repo || state.activeWorktree?.kind !== "git-worktree") return;
		await reapOwnedSessionWorktree(
			pi,
			state.repo.root,
			state.activeWorktree.path,
			ctx.sessionManager.getSessionId(),
		).catch(() => {});
	});
}
