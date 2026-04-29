/**
 * /worktree command — switch the active Basecamp worktree.
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import type { SessionState } from "../../../platform/config";
import { activateWorktree } from "../runtime/session";
import { listWorktrees, type WorktreeSummary } from "../runtime/worktree";

function formatWorktreeChoice(wt: WorktreeSummary, activeLabel: string | null): string {
	const marker = wt.label === activeLabel ? " (active)" : "";
	return `${wt.label}${marker} — ${wt.branch}`;
}

async function getRegisteredWorktrees(
	pi: ExtensionAPI,
	state: SessionState,
	ctx: ExtensionContext,
): Promise<WorktreeSummary[] | null> {
	if (!state.isRepo) {
		ctx.ui.notify("/worktree requires a git repository", "error");
		return null;
	}

	try {
		const worktrees = await listWorktrees(pi, state.primaryDir, state.repoName);
		if (worktrees.length === 0) {
			ctx.ui.notify(`No Basecamp worktrees registered for ${state.repoName}`, "info");
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

	const choice = await ctx.ui.select("Switch active worktree", choices);
	return choice ? (labelsByChoice.get(choice) ?? null) : null;
}

export function registerWorktreeCommand(pi: ExtensionAPI, getState: () => SessionState): void {
	pi.registerCommand("worktree", {
		description: "Switch the active Basecamp worktree",
		handler: async (args, ctx) => {
			const state = getState();
			const worktrees = await getRegisteredWorktrees(pi, state, ctx);
			if (!worktrees) return;

			const requestedLabel = args?.trim() || null;
			let label = requestedLabel;

			if (!label) {
				label = await selectWorktreeLabel(ctx, worktrees, state.worktreeLabel);
				if (!label) {
					ctx.ui.notify("Worktree switch cancelled", "info");
					return;
				}
			}

			const match = worktrees.find((wt) => wt.label === label);
			if (!match) {
				ctx.ui.notify(`Unknown Basecamp worktree '${label}'. Use /worktree to choose a registered worktree.`, "error");
				return;
			}

			if (state.worktreeLabel === match.label && state.worktreeDir === match.path) {
				ctx.ui.notify(`Worktree already active: ${match.label}`, "info");
				return;
			}

			try {
				const wt = await activateWorktree(pi, match.label);
				ctx.ui.notify(`Worktree active: ${wt.label} (${wt.branch})`, "info");
			} catch (err) {
				const msg = err instanceof Error ? err.message : String(err);
				ctx.ui.notify(`Worktree switch failed: ${msg}`, "error");
			}
		},
	});
}
