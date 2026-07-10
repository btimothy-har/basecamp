/**
 * Implementation handoff — execution posture selection, worktree targeting,
 * and the deferred handoff message (with optional pre-handoff compaction).
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { shortSessionId } from "#core/session/session-id.ts";
import {
	getWorkspaceState,
	listWorkspaceWorktrees,
	requireWorkspaceState,
	type WorkspaceWorktree,
} from "#core/workspace/service.ts";
import type { TaskStatus } from "../../lifecycle/index.ts";
import { collectApprovedNotes } from "../draft/index.ts";
import type { PlanDraft } from "../review/index.ts";
import {
	buildExecutionWorktreeChoices,
	CUSTOM_WORKTREE_CHOICE,
	customWorktreeTarget,
	type ExecutionWorktreeTarget,
	suggestWorktreeTarget,
} from "./worktree-choices.ts";

export type ImplementationMode = "supervisor" | "executor";

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
	mode: ImplementationMode;
	worktree: HandoffWorktreeContext;
	plan: HandoffPlanContext;
}

const IMPLEMENTATION_MODE_CHOICES = ["Execute as Supervisor", "Execute as IC/executor"] as const;

export async function selectImplementationMode(ctx: ExtensionContext): Promise<ImplementationMode | null> {
	if (!ctx.hasUI) return null;

	const choice = await ctx.ui.select("Execute approved plan as", [...IMPLEMENTATION_MODE_CHOICES]);
	if (choice === "Execute as Supervisor") return "supervisor";
	if (choice === "Execute as IC/executor") return "executor";
	return null;
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

export function buildHandoffMessage(mode: ImplementationMode): string {
	if (mode === "supervisor") {
		return "Plan looks good — proceed as supervisor. Delegate bounded investigation and implementation to subagents; keep synthesis, decisions, and integration here.";
	}

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
	mode: ImplementationMode,
	worktree: HandoffWorktreeResult,
): PendingImplementationHandoff {
	const repo = requireWorkspaceState().repo;
	if (!repo) throw new Error("Implementation handoff requires a git repository");
	return {
		mode,
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
		`Mode: ${handoff.mode}`,
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

export function shouldReuseActiveWorktreeForHandoff(
	agentRole: string | null,
	activeWorktree: WorkspaceWorktree | null,
): boolean {
	return agentRole === "workstream_agent" && activeWorktree !== null;
}
