/**
 * Plan — structured proposal with user review before execution.
 *
 * The plan() tool submits a structured plan (goal, context, design, success,
 * boundaries, tasks) and blocks until the user reviews it via an auto-pop
 * overlay. On approval it seeds the goal cycle; implementation plans then hand
 * off to an execution worktree, analysis plans stay in analysis mode. On
 * feedback, returns structured feedback for revision.
 *
 * Subagent sessions have no reviewer and already run in their own isolated
 * workspace, so their plans auto-approve: the goal cycle starts immediately
 * and execution proceeds in place — no review overlay, no worktree handoff.
 * Without this, a headless plan() could never be approved (fresh reviews only
 * become approved through the overlay) and every call was a dead end.
 *
 * The tool is thin: it drives draft → review → approve, delegates the worktree
 * choreography to runHandoff, and maps the outcome to its result.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { getAgentMode, setAgentMode } from "#core/agent-mode/index.ts";
import { isSubagent } from "#core/host/env.ts";
import { withHerdrBlocked } from "#core/ui/herdr.ts";
import { startGoalCycle } from "#tasks/lifecycle/goal-cycle.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import type { PlanDraft } from "#tasks/schemas/plan.ts";
import type { GoalCycle } from "#tasks/schemas/task.ts";
import {
	approveDraft,
	buildApprovedResult,
	buildDraft,
	buildFeedbackResult,
	isAllApproved,
} from "#tasks/workflows/draft.ts";
import { createHandoffLatch, dispatchImplementationHandoff } from "#tasks/workflows/handoff/dispatch.ts";
import {
	buildHandoffMessage,
	buildPendingImplementationHandoff,
	buildWorktreeActivationFailedResult,
	type PendingImplementationHandoff,
	runHandoff,
} from "#tasks/workflows/handoff/index.ts";
import { showReviewOverlay } from "#tasks/workflows/review/index.ts";
import { renderPartial, renderSuccess } from "./render.ts";

export interface PlanAccess {
	getDraft(): PlanDraft | null;
	/** True while an approved implementation handoff still owes the session a restart. */
	isHandoffActive(): boolean;
}

/**
 * The two collaborators the approval path cannot otherwise be driven through: the
 * review overlay only resolves through real UI, and the handoff shells out to git.
 * Injecting them is what makes the latch wiring testable.
 */
export interface PlanDeps {
	review?: (draft: PlanDraft, ctx: ExtensionContext) => Promise<"submit" | "decline">;
	handoff?: typeof runHandoff;
	/** Injectable for tests; agent depth is immutable per process, so this is resolved once at registration. */
	isSubagent?: () => boolean;
}

function cancelledResult(next_step: string) {
	return {
		content: [{ type: "text" as const, text: JSON.stringify({ status: "handoff_cancelled", next_step }) }],
		details: undefined,
	};
}

export function registerPlan(pi: ExtensionAPI, runtime: TasksRuntime, deps: PlanDeps = {}): PlanAccess {
	const review = deps.review ?? showReviewOverlay;
	const handoff = deps.handoff ?? runHandoff;
	const subagentSession = (deps.isSubagent ?? isSubagent)();
	let draft: PlanDraft | null = null;
	let pendingImplementationHandoff: PendingImplementationHandoff | null = null;
	const handoffLatch = createHandoffLatch();

	pi.on("agent_end", async (_event, ctx) => {
		if (!pendingImplementationHandoff) return;
		const handoff = pendingImplementationHandoff;
		pendingImplementationHandoff = null;

		// Pi clears isStreaming after awaited agent_end handlers finish; defer to the next macrotask.
		setTimeout(() => {
			dispatchImplementationHandoff({
				handoff,
				contextUsagePercent: ctx.getContextUsage()?.percent,
				compact: (request) => ctx.compact(request),
				send: () => {
					handoffLatch.disarm();
					pi.sendUserMessage(buildHandoffMessage());
				},
			});
		}, 0);
	});

	pi.registerTool({
		name: "plan",
		label: "Plan",
		description: subagentSession
			? "Submit a structured plan for this dispatched run. The plan is auto-approved: it sets the goal and " +
				"task list in one call, and execution proceeds immediately in the current workspace."
			: "Submit a structured plan for user review. Blocks until the user approves or provides feedback. " +
				"On approval, creates the goal and tasks. Analysis plans stay in analysis mode; " +
				"implementation plans hand off to an execution worktree for direct implementation. " +
				"On feedback, returns structured feedback for revision.",
		promptSnippet: "Submit a structured plan for review, approval, and work handoff",
		parameters: Type.Object({
			goal: Type.String({ description: "Overarching objective" }),
			context: Type.String({ description: "What exists, constraints, what triggered this work" }),
			design: Type.String({ description: "Approach, patterns, trade-offs considered" }),
			success: Type.String({ description: "What done looks like (plan-level success criteria)" }),
			boundaries: Type.String({ description: "What is explicitly out of scope" }),
			worktreeSlug: Type.Optional(
				Type.String({
					description:
						"Internal metadata for worktree label suggestion; not shown in plan review. Short kebab-case slug, no session prefix.",
				}),
			),
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
					worktreeSlug: params.worktreeSlug ?? draft?.worktreeSlug ?? undefined,
				},
				params.tasks,
				draft,
			);

			if (subagentSession) {
				draft = approveDraft(draft);
			}

			let reviewResult: "submit" | "decline" = "submit";
			if (ctx.hasUI && !subagentSession) {
				const reviewDraft = draft;
				reviewResult = await withHerdrBlocked(pi, "Waiting for plan approval", () => review(reviewDraft, ctx));
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

			if (!isAllApproved(draft)) {
				return { content: [{ type: "text", text: buildFeedbackResult(draft) }], details: undefined };
			}

			const approvedTasks = draft.tasks.map((t) => ({ ...t, review: null }));
			const planRef: GoalCycle["planRef"] = {
				context: draft.context.content,
				design: draft.design.content,
				success: draft.success.content,
				boundaries: draft.boundaries.content,
			};

			if (getAgentMode() === "analysis") {
				startGoalCycle(runtime, { goal: draft.goal.content, tasks: approvedTasks, planRef, agentMode: "analysis" });
				const result = buildApprovedResult(draft, "analysis");
				draft = null;
				return { content: [{ type: "text", text: result }], details: undefined };
			}

			// A dispatched run already executes inside its own isolated workspace, so
			// there is no worktree to choose and no fresh-session handoff to schedule.
			if (subagentSession) {
				setAgentMode("work");
				startGoalCycle(runtime, { goal: draft.goal.content, tasks: approvedTasks, planRef, agentMode: "work" });
				const result = buildApprovedResult(draft, "in_place");
				draft = null;
				return { content: [{ type: "text", text: result }], details: undefined };
			}

			const outcome = await handoff(pi, ctx, { goal: draft.goal.content, worktreeSlug: draft.worktreeSlug });
			if (outcome.status === "cancelled") {
				return cancelledResult(
					"Plan approved, but an execution worktree was not selected. Seek user confirmation before implementation.",
				);
			}
			if (outcome.status === "activation_failed") {
				return {
					content: [{ type: "text", text: buildWorktreeActivationFailedResult(outcome.label, outcome.error) }],
					details: undefined,
				};
			}

			// Implementation plans hand off to work mode: the primary session implements
			// directly, delegating file-disjoint tasks to workers when useful. This replaces the
			// old supervisor/IC choice.
			setAgentMode("work");
			startGoalCycle(runtime, {
				goal: draft.goal.content,
				tasks: approvedTasks,
				planRef,
				agentMode: "work",
			});
			pendingImplementationHandoff = buildPendingImplementationHandoff(draft, outcome.worktree);
			handoffLatch.arm();

			const result = buildApprovedResult(draft, "implementation", outcome.worktree, outcome.setupSummary);
			draft = null;
			return { content: [{ type: "text", text: result }], details: undefined };
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
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
				const { Text } = require("@earendil-works/pi-tui");
				const first = result.content?.[0];
				const text = first && "text" in first ? first.text : "{}";
				const parsed = JSON.parse(text);

				if (parsed.status === "declined") {
					return new Text(theme.fg("dim", "declined"), 0, 0);
				}

				if (parsed.status === "approved") {
					const mode = parsed.plan_mode ? ` → ${parsed.plan_mode}` : "";
					return renderSuccess(`plan approved${mode}`, theme);
				}

				if (parsed.status === "handoff_cancelled") {
					return new Text(theme.fg("warning", "handoff cancelled"), 0, 0);
				}

				if (parsed.status === "worktree_activation_failed") {
					return new Text(theme.fg("error", "worktree activation failed"), 0, 0);
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
		isHandoffActive: () => handoffLatch.active,
	};
}
