/**
 * Workspace session bootstrap — generic runtime flags and session state.
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import {
	appendWorkspaceWorktreeAffinity,
	attachWorkspaceWorktreePath,
	initializeWorkspace,
	latestWorkspaceWorktreeAffinity,
	requireWorkspaceService,
	requireWorkspaceState,
	type UnsafeEditFlagResult,
	type WorkspaceWorktree,
	workspaceMatchesWorktreeAffinity,
} from "../../platform/workspace.ts";

interface WorktreeApplyOptions {
	persistAffinity?: boolean;
}

function applyWorktree(pi: ExtensionAPI, target: WorkspaceWorktree, options: WorktreeApplyOptions = {}): void {
	if (options.persistAffinity ?? true) {
		appendWorkspaceWorktreeAffinity(pi, requireWorkspaceState(), target);
	}
}

async function attachWorktree(
	pi: ExtensionAPI,
	worktreeDir: string,
	options: WorktreeApplyOptions = {},
): Promise<WorkspaceWorktree> {
	const target = await attachWorkspaceWorktreePath(worktreeDir);
	applyWorktree(pi, target, options);
	return target;
}

const WORKTREE_AFFINITY_RESTORE_REASONS = new Set<SessionStartEvent["reason"]>(["resume", "reload", "fork"]);

async function restoreWorktreeAffinity(pi: ExtensionAPI, ctx: ExtensionContext): Promise<void> {
	const workspaceState = requireWorkspaceState();
	if (!workspaceState.repo) return;

	const affinity = latestWorkspaceWorktreeAffinity(ctx.sessionManager.getBranch());
	if (!affinity || !workspaceMatchesWorktreeAffinity(workspaceState, affinity)) return;

	try {
		const wt = await attachWorktree(pi, affinity.worktree.path, { persistAffinity: false });
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

export function registerWorkspaceSession(pi: ExtensionAPI): void {
	requireWorkspaceService();

	pi.registerFlag("worktree-dir", {
		description: "Attach to an existing workspace worktree directory",
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

	pi.on("session_start", async (event, ctx) => {
		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const launchCwd = path.resolve(ctx.cwd);

		const { unsafeEditResult } = await initializeWorkspace({
			launchCwd,
			unsafeEditFlag: pi.getFlag("unsafe-edit") === true,
			unsafeEditConstraints: {
				readOnly: pi.getFlag("read-only") === true,
				hasUI: ctx.hasUI,
				isSubagent: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0,
			},
		});

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

		notifyUnsafeEditResult(ctx, unsafeEditResult);

		const latestWorkspaceState = requireWorkspaceState();
		loadDotenv(latestWorkspaceState.repo?.root ?? latestWorkspaceState.launchCwd);
		await fs.mkdir(path.join(latestWorkspaceState.scratchDir, "pull-requests"), { recursive: true });
	});
}
