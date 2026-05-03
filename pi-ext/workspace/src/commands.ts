/**
 * /worktree command — switch the active workspace worktree.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { appendWorkspaceAffinity } from "./affinity.ts";
import { requireWorkspaceRuntime } from "./service.ts";
import { listWorktrees, type WorktreeSummary } from "./worktree.ts";

function formatWorktreeChoice(wt: WorktreeSummary, activeLabel: string | null): string {
	const marker = wt.label === activeLabel ? " (active)" : "";
	return `${wt.label}${marker} — ${wt.branch}`;
}

async function getRegisteredWorktrees(pi: ExtensionAPI, ctx: ExtensionContext): Promise<WorktreeSummary[] | null> {
	const workspace = requireWorkspaceRuntime();
	const state = workspace.current();
	if (!state?.repo) {
		ctx.ui.notify("/worktree requires a git repository", "error");
		return null;
	}

	try {
		const worktrees = await listWorktrees(pi, state.repo.root, state.repo.name);
		if (worktrees.length === 0) {
			ctx.ui.notify(`No workspace worktrees registered for ${state.repo.name}`, "info");
			return null;
		}
		return worktrees;
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		ctx.ui.notify(`Failed to list worktrees: ${msg}`, "error");
		return null;
	}
}

async function selectWorktreeLabel(
	ctx: ExtensionContext,
	worktrees: WorktreeSummary[],
	activeLabel: string | null,
): Promise<string | null> {
	if (!ctx.hasUI) return null;

	const labelsByChoice = new Map<string, string>();
	const choices = worktrees.map((wt) => {
		const choice = formatWorktreeChoice(wt, activeLabel);
		labelsByChoice.set(choice, wt.label);
		return choice;
	});

	const choice = await ctx.ui.select("Switch active workspace worktree", choices);
	return choice ? (labelsByChoice.get(choice) ?? null) : null;
}

export function registerWorktreeCommand(pi: ExtensionAPI): void {
	pi.registerCommand("worktree", {
		description: "Switch the active workspace worktree",
		handler: async (args, ctx) => {
			const workspace = requireWorkspaceRuntime();
			const state = workspace.current();
			const worktrees = await getRegisteredWorktrees(pi, ctx);
			if (!worktrees || !state?.repo) return;

			const activeTarget = state.executionTarget;
			const requestedLabel = args?.trim() || null;
			let label = requestedLabel;

			if (!label) {
				label = await selectWorktreeLabel(ctx, worktrees, activeTarget?.label ?? null);
				if (!label) {
					ctx.ui.notify("Worktree switch cancelled", "info");
					return;
				}
			}

			const match = worktrees.find((wt) => wt.label === label);
			if (!match) {
				ctx.ui.notify(`Unknown workspace worktree '${label}'. Use /worktree to choose a registered worktree.`, "error");
				return;
			}

			if (activeTarget?.label === match.label && activeTarget.path === match.path) {
				ctx.ui.notify(`Worktree already active: ${match.label}`, "info");
				return;
			}

			try {
				const target = await workspace.attachExecutionTargetPath(match.path);
				appendWorkspaceAffinity(pi, workspace.require(), target);
				ctx.ui.notify(`Worktree active: ${target.label} (${target.branch ?? "detached"})`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`Worktree switch failed: ${msg}`, "error");
			}
		},
	});
}
