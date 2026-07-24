/**
 * /worktree command — create a new worktree, switch the active one, or prune dormant ones.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { listWorktrees, resolveAvailableWorktreeLabel, type WorktreeSummary } from "../../git/worktrees/crud.ts";
import { executionWorktreeTarget } from "../../git/worktrees/target.ts";
import { readWorktreeSetupCommand } from "../../host/config.ts";
import { shortSessionId } from "../../session/session-id.ts";
import { runWorktreePrune } from "./prune.ts";
import { requireWorkspaceRuntime, type WorkspaceRuntimeService } from "./runtime.ts";
import { runWorktreeSetup, shouldRunWorktreeSetup } from "./setup.ts";
import type { RepoContext, WorkspaceWorktree } from "./state.ts";

export const CREATE_CHOICE = "Create new worktree";

function formatWorktreeChoice(wt: WorktreeSummary, activeLabel: string | null): string {
	const marker = wt.label === activeLabel ? " (active)" : "";
	return `${wt.label}${marker} — ${wt.branch}`;
}

export type WorktreeSelection = { kind: "create" } | { kind: "switch"; label: string };

export async function promptWorktreeChoice(
	ctx: ExtensionContext,
	worktrees: WorktreeSummary[],
	activeLabel: string | null,
): Promise<WorktreeSelection | null> {
	if (!ctx.hasUI) return null;

	const labelsByChoice = new Map<string, string>();
	const choices = [CREATE_CHOICE];
	for (const wt of worktrees) {
		const choice = formatWorktreeChoice(wt, activeLabel);
		labelsByChoice.set(choice, wt.label);
		choices.push(choice);
	}

	const choice = await ctx.ui.select("Worktree", choices);
	if (!choice) return null;
	if (choice === CREATE_CHOICE) return { kind: "create" };
	const label = labelsByChoice.get(choice);
	return label ? { kind: "switch", label } : null;
}

async function switchWorktree(
	ctx: ExtensionContext,
	workspace: WorkspaceRuntimeService,
	worktrees: WorktreeSummary[],
	active: WorkspaceWorktree | null,
	label: string,
): Promise<void> {
	const match = worktrees.find((wt) => wt.label === label);
	if (!match) {
		ctx.ui.notify(`Unknown workspace worktree '${label}'. Use /worktree to choose or create one.`, "error");
		return;
	}
	if (active?.label === match.label && active.path === match.path) {
		ctx.ui.notify(`Worktree already active: ${match.label}`, "info");
		return;
	}
	try {
		const target = await workspace.attachWorktreePath(match.path);
		ctx.ui.notify(`Worktree active: ${target.label} (${target.branch ?? "detached"})`, "info");
	} catch (err) {
		ctx.ui.notify(`Worktree switch failed: ${err instanceof Error ? err.message : String(err)}`, "error");
	}
}

/** Run the per-repo setup hook for a freshly created worktree; best-effort, never blocks activation. */
async function runCreatedWorktreeSetup(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	repo: RepoContext,
	wt: WorkspaceWorktree,
): Promise<void> {
	const setupCommand = readWorktreeSetupCommand(repo.name);
	if (!shouldRunWorktreeSetup(wt.created, setupCommand)) return;
	ctx.ui.notify("basecamp: provisioning worktree — running setup (up to 3 min)…", "info");
	try {
		const result = await runWorktreeSetup(pi, {
			command: setupCommand as string,
			worktreeDir: wt.path,
			repoRoot: repo.root,
		});
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

export async function createWorktreeFlow(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	workspace: WorkspaceRuntimeService,
	repo: RepoContext,
): Promise<void> {
	const input = await ctx.ui.input("New worktree slug (e.g. add-caching)", "");
	const slug = input?.trim();
	if (!slug) {
		ctx.ui.notify("Worktree creation cancelled", "info");
		return;
	}

	const target = executionWorktreeTarget(slug, shortSessionId(ctx.sessionManager.getSessionId()));

	try {
		const label = await resolveAvailableWorktreeLabel(
			pi,
			repo.root,
			repo.name,
			target.worktreeLabel,
			target.branchName,
		);
		const wt = await workspace.activateWorktree(label, target.branchName);
		await runCreatedWorktreeSetup(pi, ctx, repo, wt);
		ctx.ui.notify(`Worktree active: ${wt.label} (${wt.branch ?? "detached"})`, "info");
	} catch (err) {
		ctx.ui.notify(`Worktree creation failed: ${err instanceof Error ? err.message : String(err)}`, "error");
	}
}

export function registerWorktreeCommand(pi: ExtensionAPI): void {
	pi.registerCommand("worktree", {
		description: "Create or switch the active workspace worktree, or `/worktree prune` to reclaim dormant ones",
		handler: async (args, ctx) => {
			const trimmed = args?.trim() ?? "";
			if (trimmed === "prune") {
				await runWorktreePrune(pi, ctx);
				return;
			}

			const workspace = requireWorkspaceRuntime();
			const state = workspace.current();
			if (!state?.repo) {
				ctx.ui.notify("/worktree requires a git repository", "error");
				return;
			}

			let worktrees: WorktreeSummary[];
			try {
				worktrees = await listWorktrees(pi, state.repo.root, state.repo.name);
			} catch (err) {
				ctx.ui.notify(`Failed to list worktrees: ${err instanceof Error ? err.message : String(err)}`, "error");
				return;
			}

			// Explicit `/worktree <label>` switches to a registered worktree; create is dropdown-only.
			if (trimmed) {
				await switchWorktree(ctx, workspace, worktrees, state.activeWorktree, trimmed);
				return;
			}

			const selection = await promptWorktreeChoice(ctx, worktrees, state.activeWorktree?.label ?? null);
			if (!selection) {
				ctx.ui.notify("Worktree selection cancelled", "info");
				return;
			}
			if (selection.kind === "create") {
				await createWorktreeFlow(pi, ctx, workspace, state.repo);
				return;
			}
			await switchWorktree(ctx, workspace, worktrees, state.activeWorktree, selection.label);
		},
	});
}
