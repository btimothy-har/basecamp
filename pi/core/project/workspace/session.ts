/**
 * Workspace session bootstrap — generic runtime flags and session state.
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { migrateLegacyWorktrees } from "../../git/worktrees/migrate.ts";
import { sweepAgentWorktrees } from "../../git/worktrees/sweep.ts";
import { readLogseqGraphDir } from "../../host/config.ts";
import { getAgentDepth, getBasecampEnv } from "../../host/env.ts";
import { getCurrentSessionState } from "../../session/state/index.ts";
import { workspaceMatchesActiveWorktreeState } from "./affinity.ts";
import { requireWorkspaceRuntime } from "./runtime.ts";
import {
	attachWorkspaceWorktreePath,
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

async function restoreActiveWorktreeState(ctx: ExtensionContext): Promise<void> {
	const workspaceState = requireWorkspaceState();
	if (!workspaceState.repo) return;

	// Core registers first in extension.ts, so its session_start already
	// initialized state for this event.
	const activeWorktree = getCurrentSessionState().activeWorktree;
	if (!activeWorktree || !workspaceMatchesActiveWorktreeState(workspaceState, activeWorktree)) return;
	// Init already recognized this linked worktree; re-attaching would re-run validateProtectedCheckout and
	// fail on a dirty or off-branch main checkout.
	if (
		workspaceState.activeWorktree &&
		path.resolve(workspaceState.activeWorktree.path) === path.resolve(activeWorktree.worktree.path)
	) {
		return;
	}

	try {
		const wt = await attachWorktree(activeWorktree.worktree.path);
		ctx.ui.notify(`basecamp: restored worktree → ${wt.label}`, "info");
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.ui.notify(`basecamp: saved worktree restore skipped — ${msg}`, "warning");
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

		const result = await sweepAgentWorktrees(pi, state.repo.root);
		if (result.removed.length > 0) {
			ctx.ui.notify(`basecamp: reclaimed ${result.removed.length} merged agent worktree(s)`, "info");
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

		const { unsafeEditResult } = await initializeWorkspace({
			launchCwd,
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

		if (worktreeDir) {
			try {
				const wt = await attachWorktree(worktreeDir);
				ctx.ui.notify(`basecamp: worktree attached → ${wt.label}`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`basecamp: worktree attach failed — ${msg}`, "error");
			}
		} else if (WORKTREE_STATE_RESTORE_REASONS.has(event.reason)) {
			await restoreActiveWorktreeState(ctx);
		}

		notifyUnsafeEditResult(ctx, unsafeEditResult);

		const latestWorkspaceState = requireWorkspaceState();
		loadDotenv(latestWorkspaceState.repo?.root ?? latestWorkspaceState.launchCwd);
		await fs.mkdir(path.join(latestWorkspaceState.scratchDir, "pull-requests"), { recursive: true });
	});
}
