/**
 * Session — state management and session bootstrap.
 *
 * session_start:
 *   - Reads --worktree-dir / --style flags
 *   - Initializes workspace runtime from Pi's launch cwd
 *   - Detects the configured Basecamp project from workspace repo state
 *   - Attaches to an existing worktree if --worktree-dir provided
 *   - Loads .env from the repository root or launch cwd
 *   - Creates work directories
 *   - Sets BASECAMP_PROJECT for downstream tools
 */

import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, SessionStartEvent } from "@mariozechner/pi-coding-agent";
import { resolveBasecampProjectState } from "../../../platform/config";
import {
	getBasecampProjectState,
	requireBasecampProjectState,
	resetBasecampProjectRuntime,
	setBasecampProjectState,
} from "../../../platform/project";
import {
	appendWorkspaceWorktreeAffinity,
	attachWorkspaceWorktreePath,
	initializeWorkspace,
	latestWorkspaceWorktreeAffinity,
	registerWorkspaceAllowedRootsProvider,
	requireWorkspaceService,
	requireWorkspaceState,
	type WorkspaceWorktree,
	workspaceMatchesWorktreeAffinity,
} from "../../../platform/workspace";
import { resetAgentMode } from "./mode";

function setBasecampProjectEnv(): void {
	process.env.BASECAMP_PROJECT = getBasecampProjectState()?.projectName ?? "";
}

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

export function registerSession(pi: ExtensionAPI): void {
	requireWorkspaceService();

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

	pi.on("session_start", async (event, ctx) => {
		resetAgentMode();
		resetBasecampProjectRuntime();

		const worktreeDir = (pi.getFlag("worktree-dir") as string | undefined) ?? null;
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const launchCwd = path.resolve(ctx.cwd);

		const { state: workspaceState, unsafeEditResult } = await initializeWorkspace({
			launchCwd,
			unsafeEditFlag: pi.getFlag("unsafe-edit") === true,
			unsafeEditConstraints: {
				readOnly: pi.getFlag("read-only") === true,
				hasUI: ctx.hasUI,
				isSubagent: Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0,
			},
		});

		const projectState = resolveBasecampProjectState({
			repoRoot: workspaceState.repo?.root ?? workspaceState.launchCwd,
			isRepo: workspaceState.repo !== null,
			styleOverride,
		});
		setBasecampProjectState(projectState);
		setBasecampProjectEnv();

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

		if (unsafeEditResult === "ignored-read-only") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored because --read-only is active", "warning");
		} else if (unsafeEditResult === "ignored-subagent") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored in subagent sessions", "warning");
		} else if (unsafeEditResult === "ignored-non-interactive") {
			ctx.ui.notify("basecamp: --unsafe-edit ignored without interactive UI", "warning");
		}

		const dotenvRoot = workspaceState.repo?.root ?? workspaceState.launchCwd;
		const dotenvPath = path.join(dotenvRoot, ".env");
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

		await fs.mkdir(path.join(workspaceState.scratchDir, "pull-requests"), { recursive: true });

		const latestWorkspaceState = requireWorkspaceState();
		const latestProjectState = requireBasecampProjectState();
		const repoName = latestWorkspaceState.repo?.name ?? path.basename(latestWorkspaceState.scratchDir);
		const parts = [`repo=${repoName}`];
		if (latestProjectState.projectName) parts.push(`project=${latestProjectState.projectName}`);
		if (latestWorkspaceState.activeWorktree?.label) parts.push(`worktree=${latestWorkspaceState.activeWorktree.label}`);
		ctx.ui.notify(`basecamp: ${parts.join(", ")}`, "info");
	});
}
