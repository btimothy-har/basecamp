/**
 * Plan draft building and review-result serialization.
 *
 * Re-submissions diff against the previous draft — unchanged approved sections
 * keep their ✓ status, changed sections reset to ★ (needs re-review).
 */

import type { ReviewState, TaskStatus } from "../tasks/tasks.ts";
import { computeGoalContextReview, computeSectionReview, freshReview, tasksMatch } from "./draft-logic.ts";
import type { HandoffWorktreeResult, ImplementationMode } from "./handoff.ts";
import type { PlanDraft } from "./review.ts";
import { SECTION_NAMES } from "./review.ts";
import type { WorktreeSetupSummary } from "./worktree-setup.ts";

export type ApprovedPlanMode = "analysis" | ImplementationMode;

export function buildDraft(
	params: {
		goal: string;
		context: string;
		design: string;
		success: string;
		boundaries: string;
		worktreeSlug?: string;
	},
	tasks: { label: string; description: string; criteria: string }[],
	previous: PlanDraft | null,
): PlanDraft {
	const goalContextState = computeGoalContextReview(
		params.goal,
		params.context,
		previous ? { goal: previous.goal, context: previous.context } : null,
	);

	// Tasks are reviewed as a collective unit — preserve approval if list is unchanged
	function collectiveTasksReview(): ReviewState {
		if (!previous) return freshReview();
		if (tasksMatch(tasks, previous.tasks) && previous.tasksReview.approved) {
			return { approved: true, feedback: null };
		}
		return freshReview();
	}

	return {
		goal: { content: params.goal, review: goalContextState },
		context: { content: params.context, review: goalContextState },
		design: { content: params.design, review: computeSectionReview(params.design, previous?.design ?? null) },
		success: { content: params.success, review: computeSectionReview(params.success, previous?.success ?? null) },
		boundaries: {
			content: params.boundaries,
			review: computeSectionReview(params.boundaries, previous?.boundaries ?? null),
		},
		worktreeSlug: params.worktreeSlug ?? null,
		tasks: tasks.map((t) => ({
			label: t.label,
			description: t.description,
			criteria: t.criteria,
			notes: null,
			status: "pending" as TaskStatus,
			review: null,
		})),
		tasksReview: collectiveTasksReview(),
	};
}

export function isAllApproved(draft: PlanDraft): boolean {
	for (const name of SECTION_NAMES) {
		if (!draft[name].review.approved) return false;
	}
	if (!draft.tasksReview.approved) return false;
	return true;
}

export function buildFeedbackResult(draft: PlanDraft): string {
	const approved: Record<string, boolean | null> = {};
	const revisions: Record<string, string> = {};
	const notes: Record<string, string> = {};
	for (const name of SECTION_NAMES) {
		const r = draft[name].review;
		approved[name] = r.approved;
		if (r.feedback && !r.approved) revisions[name] = r.feedback;
		if (r.feedback && r.approved) notes[name] = r.feedback;
	}

	// Tasks are reviewed collectively
	const tr = draft.tasksReview;
	approved.tasks = tr.approved;
	if (tr.feedback && !tr.approved) revisions.tasks = tr.feedback;
	if (tr.feedback && tr.approved) notes.tasks = tr.feedback;

	const result: Record<string, unknown> = {
		status: "feedback",
		approved,
		revisions,
	};

	// Include approved-with-notes so agent sees them alongside revisions
	if (Object.keys(notes).length > 0) result.notes = notes;

	return JSON.stringify(result);
}

export function collectApprovedNotes(draft: PlanDraft): Record<string, string> {
	const notes: Record<string, string> = {};
	for (const name of SECTION_NAMES) {
		const r = draft[name].review;
		if (r.approved && r.feedback) notes[name] = r.feedback;
	}

	if (draft.tasksReview.approved && draft.tasksReview.feedback) {
		notes.tasks = draft.tasksReview.feedback;
	}

	return notes;
}

export function buildApprovedResult(
	draft: PlanDraft,
	mode: ApprovedPlanMode,
	worktree?: HandoffWorktreeResult,
	setupSummary?: WorktreeSetupSummary,
): string {
	const notes = collectApprovedNotes(draft);

	const tasks: Record<number, { label: string; status: string; criteria: string }> = {};
	for (let i = 0; i < draft.tasks.length; i++) {
		const t = draft.tasks[i]!;
		tasks[i] = { label: t.label, status: t.status, criteria: t.criteria };
	}

	const result: Record<string, unknown> = {
		status: "approved",
		goal: draft.goal.content,
		context: draft.context.content,
		design: draft.design.content,
		success: draft.success.content,
		boundaries: draft.boundaries.content,
		progress: {
			completed: 0,
			deleted: 0,
			total: draft.tasks.length,
		},
		tasks,
	};

	if (mode === "analysis") {
		result.plan_mode = "analysis";
		result.next_step = "Analysis plan approved, you may begin executing the analysis tasks.";
	} else {
		result.implementation_mode = mode;
		result.handoff_status = "scheduled";
		result.next_step =
			"Plan has been approved. Do not start implementation; wait for the user's confirmation to start work. Acknowledge and end the turn.";
	}

	if (worktree) {
		result.worktree = {
			label: worktree.label,
			path: worktree.worktreeDir,
			branch: worktree.branch,
			created: worktree.created,
		};
	}

	if (worktree && setupSummary) result.worktree_setup = setupSummary;

	// Only include notes if any exist
	if (Object.keys(notes).length > 0) result.notes = notes;

	return JSON.stringify(result);
}
