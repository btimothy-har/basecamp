/**
 * Workspace session bootstrap — generic runtime flags and session state.
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import { readLogseqGraphDir } from "pi-core/platform/config.ts";
import {
	attachWorkspaceWorktreePath,
	initializeWorkspace,
	registerWorkspaceAllowedRootsProvider,
	requireWorkspaceService,
	requireWorkspaceState,
	type UnsafeEditFlagResult,
	type WorkspaceWorktree,
} from "pi-core/platform/workspace.ts";
import { ensureCurrentSessionStateForEvent } from "pi-core/state/index.ts";
import { workspaceMatchesActiveWorktreeState } from "pi-core/workspace/affinity.ts";
import { migrateLegacyWorktrees } from "pi-core/workspace/migrate.ts";

async function attachWorktree(worktreeDir: string): Promise<WorkspaceWorktree> {
	return attachWorkspaceWorktreePath(worktreeDir);
}

const WORKTREE_STATE_RESTORE_REASONS = new Set<SessionStartEvent["reason"]>(["resume", "reload", "fork"]);

async function restoreActiveWorktreeState(event: SessionStartEvent, ctx: ExtensionContext): Promise<void> {
	const workspaceState = requireWorkspaceState();
	if (!workspaceState.repo) return;

	const activeWorktree = ensureCurrentSessionStateForEvent(event, ctx).activeWorktree;
	if (!activeWorktree || !workspaceMatchesActiveWorktreeState(workspaceState, activeWorktree)) return;

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
	requireWorkspaceService();
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

	pi.on("session_start", async (event, ctx) => {
		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const launchCwd = path.resolve(ctx.cwd);
		const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

		const { unsafeEditResult } = await initializeWorkspace({
			launchCwd,
			unsafeEditFlag: pi.getFlag("unsafe-edit") === true,
			unsafeEditConstraints: {
				readOnly: pi.getFlag("read-only") === true,
				hasUI: ctx.hasUI,
				isSubagent,
			},
		});

		await migrateLegacyWorktreesForSession(pi, ctx, launchCwd, isSubagent);

		if (worktreeDir) {
			try {
				const wt = await attachWorktree(worktreeDir);
				ctx.ui.notify(`basecamp: worktree attached → ${wt.label}`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`basecamp: worktree attach failed — ${msg}`, "error");
			}
		} else if (WORKTREE_STATE_RESTORE_REASONS.has(event.reason)) {
			await restoreActiveWorktreeState(event, ctx);
		}

		notifyUnsafeEditResult(ctx, unsafeEditResult);

		const latestWorkspaceState = requireWorkspaceState();
		loadDotenv(latestWorkspaceState.repo?.root ?? latestWorkspaceState.launchCwd);
		await fs.mkdir(path.join(latestWorkspaceState.scratchDir, "pull-requests"), { recursive: true });
	});
}
