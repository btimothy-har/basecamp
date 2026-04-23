/**
 * Plan — structured proposal with user review before execution.
 *
 * The plan() tool submits a structured plan (goal, context, design, success,
 * boundaries, tasks) and blocks until the user reviews it via an auto-pop
 * overlay. On approval, creates a GoalCycle with planRef and populates tasks.
 * On feedback, returns structured feedback for the agent to revise.
 *
 * Re-submissions diff against the previous draft — unchanged approved sections
 * keep their ✓ status, changed sections reset to ★ (needs re-review).
 */

import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import type { PlanDraft, SectionName } from "./review";
import { SECTION_NAMES, showPlanReadOnly, showReviewOverlay } from "./review";
import type { GoalCycle, ReviewState, TaskStatus, TasksAccess } from "./tasks";

// ============================================================================
// Draft diffing — preserve approvals on unchanged content
// ============================================================================

function freshReview(): ReviewState {
	return { approved: null, feedback: null };
}

function tasksMatch(tasks: { label: string; description: string; criteria: string }[], previous: PlanDraft): boolean {
	if (tasks.length !== previous.tasks.length) return false;
	for (let i = 0; i < tasks.length; i++) {
		const curr = tasks[i]!;
		const prev = previous.tasks[i]!;
		if (curr.label !== prev.label || curr.description !== prev.description || curr.criteria !== prev.criteria) {
			return false;
		}
	}
	return true;
}

function buildDraft(
	params: { goal: string; context: string; design: string; success: string; boundaries: string },
	tasks: { label: string; description: string; criteria: string }[],
	previous: PlanDraft | null,
): PlanDraft {
	function sectionReview(name: SectionName, content: string): ReviewState {
		if (!previous) return freshReview();
		const prev = previous[name];
		if (prev.content === content && prev.review.approved) {
			return { approved: true, feedback: null };
		}
		return freshReview();
	}

	// Tasks are reviewed as a collective unit — preserve approval if list is unchanged
	function collectiveTasksReview(): ReviewState {
		if (!previous) return freshReview();
		if (tasksMatch(tasks, previous) && previous.tasksReview.approved) {
			return { approved: true, feedback: null };
		}
		return freshReview();
	}

	return {
		goal: { content: params.goal, review: sectionReview("goal", params.goal) },
		context: { content: params.context, review: sectionReview("context", params.context) },
		design: { content: params.design, review: sectionReview("design", params.design) },
		success: { content: params.success, review: sectionReview("success", params.success) },
		boundaries: { content: params.boundaries, review: sectionReview("boundaries", params.boundaries) },
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

// ============================================================================
// Review result builders
// ============================================================================

function isAllApproved(draft: PlanDraft): boolean {
	for (const name of SECTION_NAMES) {
		if (!draft[name].review.approved) return false;
	}
	if (!draft.tasksReview.approved) return false;
	return true;
}

function buildFeedbackResult(draft: PlanDraft): string {
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

function buildApprovedResult(draft: PlanDraft): string {
	// Collect user notes from approved-with-feedback sections
	const notes: Record<string, string> = {};
	for (const name of SECTION_NAMES) {
		const r = draft[name].review;
		if (r.approved && r.feedback) notes[name] = r.feedback;
	}

	// Include collective task feedback if present
	if (draft.tasksReview.approved && draft.tasksReview.feedback) {
		notes.tasks = draft.tasksReview.feedback;
	}

	const tasks: Record<number, { label: string; status: string; criteria: string }> = {};
	for (let i = 0; i < draft.tasks.length; i++) {
		const t = draft.tasks[i]!;
		tasks[i] = { label: t.label, status: t.status, criteria: t.criteria };
	}

	const result: Record<string, unknown> = {
		status: "approved",
		next_step: "Plan approved. Begin implementing.",
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

	// Only include notes if any exist
	if (Object.keys(notes).length > 0) result.notes = notes;

	return JSON.stringify(result);
}

// ============================================================================
// Tool render helpers
// ============================================================================

function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

function renderPartial(theme: Theme) {
	const { Text } = require("@mariozechner/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

// ============================================================================
// Types (exported)
// ============================================================================

export interface PlanAccess {
	getDraft(): PlanDraft | null;
}

// ============================================================================
// Registration
// ============================================================================

export function registerPlan(pi: ExtensionAPI, tasksAccess: TasksAccess): PlanAccess {
	let draft: PlanDraft | null = null;

	pi.registerTool({
		name: "plan",
		label: "Plan",
		description:
			"Submit a structured plan for user review. Blocks until the user approves or provides feedback. " +
			"On approval, creates the goal and tasks. On feedback, returns structured feedback for revision.",
		promptSnippet: "Submit a structured plan for review and approval",
		parameters: Type.Object({
			goal: Type.String({ description: "Overarching objective" }),
			context: Type.String({ description: "What exists, constraints, what triggered this work" }),
			design: Type.String({ description: "Approach, patterns, trade-offs considered" }),
			success: Type.String({ description: "What done looks like (plan-level success criteria)" }),
			boundaries: Type.String({ description: "What is explicitly out of scope" }),
			tasks: Type.Array(
				Type.Object({
					label: Type.String({ description: "Short task name" }),
					description: Type.String({ description: "What this task involves and why" }),
					criteria: Type.String({ description: "What done looks like for this task" }),
				}),
				{ description: "Ordered list of tasks", minItems: 1 },
			),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			draft = buildDraft(
				{
					goal: params.goal,
					context: params.context,
					design: params.design,
					success: params.success,
					boundaries: params.boundaries,
				},
				params.tasks,
				draft,
			);

			let reviewResult: "submit" | "decline" = "submit";
			if (ctx.hasUI) {
				reviewResult = await showReviewOverlay(draft, ctx);
			}

			if (reviewResult === "decline") {
				draft = null;
				return {
					content: [
						{
							type: "text",
							text: JSON.stringify({ status: "declined", message: "User declined to review the plan." }),
						},
					],
					details: undefined,
				};
			}

			if (isAllApproved(draft)) {
				const approvedTasks = draft.tasks.map((t) => ({ ...t, review: null }));
				const planRef: GoalCycle["planRef"] = {
					context: draft.context.content,
					design: draft.design.content,
					success: draft.success.content,
					boundaries: draft.boundaries.content,
				};

				tasksAccess.activateGoalCycle(draft.goal.content, approvedTasks, planRef);

				const result = buildApprovedResult(draft);
				draft = null;
				return {
					content: [{ type: "text", text: result }],
					details: undefined,
				};
			}

			return {
				content: [{ type: "text", text: buildFeedbackResult(draft) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const goal = (args.goal as string) || "...";
			const preview = goal.length > 50 ? `${goal.slice(0, 50)}...` : goal;
			const taskCount = (args.tasks as unknown[])?.length ?? 0;
			return new Text(
				theme.fg("toolTitle", theme.bold("plan ")) + theme.fg("dim", `${preview} (${taskCount} tasks)`),
				0,
				0,
			);
		},
		renderResult(result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			try {
				const { Text } = require("@mariozechner/pi-tui");
				const first = result.content?.[0];
				const text = first && "text" in first ? first.text : "{}";
				const parsed = JSON.parse(text);

				if (parsed.status === "declined") {
					return new Text(theme.fg("dim", "declined"), 0, 0);
				}

				if (parsed.status === "approved") {
					return renderSuccess("plan approved", theme);
				}

				if (parsed.status === "feedback") {
					const approved = parsed.approved ?? {};
					const totalItems = Object.keys(approved).length;
					const totalApproved = Object.values(approved).filter((v) => v === true).length;
					return new Text(theme.fg("dim", `${totalItems} items, ${totalApproved} approved`), 0, 0);
				}

				return renderSuccess("plan processed", theme);
			} catch {
				return renderSuccess("plan processed", theme);
			}
		},
	});

	return {
		getDraft: () => draft,
	};
}

// ============================================================================
// /show-plan command — view or re-review plan
// ============================================================================

export function registerPlanCommands(pi: ExtensionAPI, tasksAccess: TasksAccess, plan: PlanAccess): void {
	pi.registerCommand("plan", {
		description: "Start structured planning for a topic",
		handler: async (args, ctx) => {
			const topic = args?.trim() || (ctx.hasUI ? await ctx.ui.input("What do you want to plan?") : undefined);
			if (!topic) {
				ctx.ui.notify("Usage: /plan <topic>", "error");
				return;
			}
			pi.sendUserMessage(
				`I want to plan: ${topic}\n\nInvoke the \`planning\` skill and follow its full process. Do not skip phases — explore the problem space first, discuss approach with me, then formalise via \`plan()\`.`,
			);
		},
	});

	pi.registerCommand("show-plan", {
		description: "View current plan draft or approved plan",
		handler: async (_args, ctx) => {
			const draft = plan.getDraft();

			if (draft) {
				if (ctx.hasUI) {
					await showReviewOverlay(draft, ctx);
					ctx.ui.notify("Review updated. Agent will see feedback on next turn.", "info");
				}
				return;
			}

			const planRef = tasksAccess.getPlanRef();
			if (planRef) {
				if (ctx.hasUI) {
					await showPlanReadOnly(planRef, ctx);
				}
				return;
			}

			if (ctx.hasUI) {
				ctx.ui.notify("No plan to show. Use /plan <topic> to start planning.", "info");
			}
		},
	});
}
