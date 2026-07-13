/**
 * Implementation handoff — worktree targeting and the deferred handoff
 * message (with optional pre-handoff compaction).
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { readWorktreeSetupCommand } from "#core/host/config.ts";
import { runWorktreeSetup } from "#core/project/workspace/setup.ts";
import {
	activateWorkspaceWorktree,
	getWorkspaceState,
	listWorkspaceWorktrees,
	requireWorkspaceState,
	type WorkspaceWorktree,
} from "#core/project/workspace/state.ts";
import { shortSessionId } from "#core/session/session-id.ts";
import type { PlanDraft } from "../../schemas/plan.ts";
import type { TaskStatus } from "../../schemas/task.ts";
import { collectApprovedNotes } from "../draft.ts";
import {
	buildExecutionWorktreeChoices,
	CUSTOM_WORKTREE_CHOICE,
	customWorktreeTarget,
	type ExecutionWorktreeTarget,
	suggestWorktreeTarget,
} from "./worktree-choices.ts";
import { shouldRunWorktreeSetup, type WorktreeSetupSummary, worktreeSetupSummary } from "./worktree-setup.ts";

interface HandoffTaskContext {
	index: number;
	label: string;
	description: string;
	criteria: string;
	notes: string | null;
	status: TaskStatus;
}

interface HandoffPlanContext {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
	notes: Record<string, string>;
	tasks: HandoffTaskContext[];
}

interface HandoffWorktreeContext {
	label: string;
	path: string;
	branch: string;
	created: boolean;
	repoName: string;
	repoRoot: string;
}

export type HandoffWorktreeResult = {
	worktreeDir: string;
	label: string;
	branch: string;
	created: boolean;
};

export interface PendingImplementationHandoff {
	worktree: HandoffWorktreeContext;
	plan: HandoffPlanContext;
}

export async function selectWorktreeTarget(
	ctx: ExtensionContext,
	goal: string,
	worktreeSlug: string | null,
): Promise<ExecutionWorktreeTarget | null> {
	if (!ctx.hasUI) return null;

	const workspace = getWorkspaceState();
	if (!workspace?.repo) {
		ctx.ui.notify("Execution worktrees require a git repository.", "error");
		return null;
	}

	const sessionTag = shortSessionId(ctx.sessionManager.getSessionId());
	const suggested = suggestWorktreeTarget(goal, worktreeSlug, sessionTag);
	const existing = await listWorkspaceWorktrees();
	const { choices, targetsByChoice } = buildExecutionWorktreeChoices(suggested, existing, workspace.activeWorktree);

	const choice = await ctx.ui.select("Execution worktree", choices);
	if (!choice) return null;
	if (choice === CUSTOM_WORKTREE_CHOICE) {
		const label = await ctx.ui.input("Custom worktree label", suggested.worktreeLabel);
		return label?.trim() ? customWorktreeTarget(label, sessionTag) : null;
	}
	return targetsByChoice.get(choice) ?? null;
}

export const HANDOFF_COMPACTION_THRESHOLD_PERCENT = 30;

export function buildHandoffMessage(): string {
	return "Plan looks good — proceed with direct implementation.";
}

export function buildWorktreeActivationFailedResult(label: string, error: unknown): string {
	const message = error instanceof Error ? error.message : String(error);
	return JSON.stringify({
		status: "worktree_activation_failed",
		worktree_label: label,
		message,
		next_step: "Fix the protected checkout or choose another worktree, then resubmit the approved plan.",
	});
}

export function buildPendingImplementationHandoff(
	draft: PlanDraft,
	worktree: HandoffWorktreeResult,
): PendingImplementationHandoff {
	const repo = requireWorkspaceState().repo;
	if (!repo) throw new Error("Implementation handoff requires a git repository");
	return {
		worktree: {
			label: worktree.label,
			path: worktree.worktreeDir,
			branch: worktree.branch,
			created: worktree.created,
			repoName: repo.name,
			repoRoot: repo.root,
		},
		plan: {
			goal: draft.goal.content,
			context: draft.context.content,
			design: draft.design.content,
			success: draft.success.content,
			boundaries: draft.boundaries.content,
			notes: collectApprovedNotes(draft),
			tasks: draft.tasks.map((task, index) => ({
				index,
				label: task.label,
				description: task.description,
				criteria: task.criteria,
				notes: task.notes,
				status: task.status,
			})),
		},
	};
}

export function buildHandoffCompactionInstructions(handoff: PendingImplementationHandoff): string {
	const lines: string[] = [
		"This compaction runs immediately before executing an approved Basecamp implementation plan.",
		"Focus the summary on execution-ready context; omit planning chatter that is not needed for implementation.",
		"",
		"Approved plan:",
		`Goal: ${handoff.plan.goal}`,
		`Context: ${handoff.plan.context}`,
		`Design: ${handoff.plan.design}`,
		`Success: ${handoff.plan.success}`,
		`Boundaries: ${handoff.plan.boundaries}`,
		"",
		"Execution handoff:",
		`Selected worktree: ${handoff.worktree.label} (${handoff.worktree.branch})`,
		`Worktree path: ${handoff.worktree.path}`,
		`Worktree status: ${handoff.worktree.created ? "created" : "resumed"}`,
		`Repository: ${handoff.worktree.repoName}`,
		`Protected checkout: ${handoff.worktree.repoRoot}`,
		"",
		"User feedback/notes from approval:",
	];

	const notes = Object.entries(handoff.plan.notes);
	if (notes.length === 0) {
		lines.push("- None recorded.");
	} else {
		for (const [section, note] of notes) {
			lines.push(`- ${section}: ${note}`);
		}
	}

	lines.push("", "Tasks:");
	for (const task of handoff.plan.tasks) {
		lines.push(`- [${task.index}] ${task.label} (${task.status})`);
		lines.push(`  Description: ${task.description}`);
		lines.push(`  Criteria: ${task.criteria}`);
		if (task.notes) lines.push(`  Notes: ${task.notes}`);
	}

	const nextTask =
		handoff.plan.tasks.find((task) => task.status === "active") ??
		handoff.plan.tasks.find((task) => task.status === "pending");
	lines.push("", "Next execution task:");
	if (nextTask) {
		lines.push(`- [${nextTask.index}] ${nextTask.label}`);
		lines.push(`  Description: ${nextTask.description}`);
		lines.push(`  Criteria: ${nextTask.criteria}`);
	} else {
		lines.push("- No open task was recorded; inspect the task list before editing.");
	}

	lines.push(
		"",
		"Preserve any relevant files, functions, commands, constraints, and risks mentioned in the conversation, plan sections, task descriptions, or user notes.",
		"Make the resulting summary sufficient for the next agent turn to start execution without reopening the full planning transcript.",
	);

	return lines.join("\n");
}

export function workspaceWorktreeToHandoffWorktree(target: WorkspaceWorktree): HandoffWorktreeResult {
	return {
		worktreeDir: target.path,
		label: target.label,
		branch: target.branch ?? "detached",
		created: target.created,
	};
}

export function shouldReuseActiveWorktreeForHandoff(activeWorktree: WorkspaceWorktree | null): boolean {
	// Reuse the active worktree on handoff when it is a workstream worktree
	// (copilot/<slug>); a plain session in the main checkout gets the picker.
	return activeWorktree !== null && activeWorktree.label.startsWith("copilot/");
}

export type HandoffOutcome =
	| { status: "ready"; worktree: HandoffWorktreeResult; setupSummary: WorktreeSetupSummary | undefined }
	| { status: "cancelled" }
	| { status: "activation_failed"; label: string; error: unknown };

/**
 * Resolve an execution worktree for the approved plan: reuse the active one
 * when appropriate, else prompt for a target and activate it, then run the
 * per-repo worktree setup. Returns a discriminated outcome the plan tool maps
 * to its result — the tool owns none of this choreography.
 */
export async function runHandoff(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	plan: { goal: string; worktreeSlug: string | null },
): Promise<HandoffOutcome> {
	const activeWorktree = getWorkspaceState()?.activeWorktree ?? null;

	let worktree: HandoffWorktreeResult;
	if (activeWorktree && shouldReuseActiveWorktreeForHandoff(activeWorktree)) {
		worktree = workspaceWorktreeToHandoffWorktree(activeWorktree);
	} else {
		const target = await selectWorktreeTarget(ctx, plan.goal, plan.worktreeSlug);
		if (!target) return { status: "cancelled" };
		try {
			worktree = workspaceWorktreeToHandoffWorktree(
				await activateWorkspaceWorktree(target.worktreeLabel, target.branchName),
			);
		} catch (error) {
			return { status: "activation_failed", label: target.worktreeLabel, error };
		}
	}

	return { status: "ready", worktree, setupSummary: await provisionWorktree(pi, ctx, worktree) };
}

/** Run the per-repo worktree setup command for a freshly created worktree. */
async function provisionWorktree(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	worktree: HandoffWorktreeResult,
): Promise<WorktreeSetupSummary | undefined> {
	const repo = requireWorkspaceState().repo;
	const repoRoot = repo?.root;
	const setupCommand = repo?.name ? readWorktreeSetupCommand(repo.name) : null;
	if (!repoRoot || !shouldRunWorktreeSetup(worktree.created, setupCommand)) return undefined;

	ctx.ui.notify("Provisioning worktree — running setup (up to 3 min)…", "info");
	try {
		const setupResult = await runWorktreeSetup(pi, {
			command: setupCommand as string,
			worktreeDir: worktree.worktreeDir,
			repoRoot,
		});
		if (setupResult.timedOut) {
			ctx.ui.notify("Worktree setup timed out after 3 min — continuing to handoff.", "warning");
		} else if (setupResult.exitCode !== 0) {
			ctx.ui.notify(`Worktree setup exited ${setupResult.exitCode} — continuing to handoff.`, "warning");
		} else {
			ctx.ui.notify("Worktree setup complete.", "info");
		}
		return worktreeSetupSummary(setupResult);
	} catch (err) {
		ctx.ui.notify(
			`Worktree setup error — continuing to handoff: ${err instanceof Error ? err.message : String(err)}`,
			"warning",
		);
		return undefined;
	}
}
