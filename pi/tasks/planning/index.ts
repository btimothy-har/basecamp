/**
 * Plan — structured proposal with user review before execution.
 *
 * The plan() tool submits a structured plan (goal, context, design, success,
 * boundaries, tasks) and blocks until the user reviews it via an auto-pop
 * overlay. On approval, creates a GoalCycle with planRef and populates tasks.
 * Implementation plans ask for execution posture; analysis plans stay in
 * analysis mode. On feedback, returns structured
 * feedback for the agent to revise.
 *
 * Draft building/diffing lives in draft.ts; execution handoff in handoff.ts;
 * the /show-plan command in commands.ts.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { readWorktreeSetupCommand } from "#core/platform/config.ts";
import { resolveSessionProductRoleOverride } from "#core/platform/product-role.ts";
import { activateWorkspaceWorktree, getWorkspaceState, requireWorkspaceState } from "#core/platform/workspace.ts";
import { getAgentMode, setAgentMode } from "#core/session/agent-mode.ts";
import { runWorktreeSetup } from "#core/workspace/setup.ts";
import type { GoalCycle, TasksAccess } from "../lifecycle/index.ts";
import { renderPartial, renderSuccess } from "../render.ts";
import { buildApprovedResult, buildDraft, buildFeedbackResult, isAllApproved } from "./draft/index.ts";
import {
	buildHandoffCompactionInstructions,
	buildHandoffMessage,
	buildPendingImplementationHandoff,
	buildWorktreeActivationFailedResult,
	HANDOFF_COMPACTION_THRESHOLD_PERCENT,
	type HandoffWorktreeResult,
	type PendingImplementationHandoff,
	selectImplementationMode,
	selectWorktreeTarget,
	shouldReuseActiveWorktreeForHandoff,
	workspaceWorktreeToHandoffWorktree,
} from "./handoff/index.ts";
import { shouldRunWorktreeSetup, type WorktreeSetupSummary, worktreeSetupSummary } from "./handoff/worktree-setup.ts";
import type { PlanDraft } from "./review/index.ts";
import { showReviewOverlay } from "./review/index.ts";

export { registerPlanCommands } from "./commands.ts";
export type { ImplementationMode } from "./handoff/index.ts";
export {
	buildHandoffMessage,
	shouldReuseActiveWorktreeForHandoff,
	workspaceWorktreeToHandoffWorktree,
} from "./handoff/index.ts";

export interface PlanAccess {
	getDraft(): PlanDraft | null;
}

export function registerPlan(pi: ExtensionAPI, tasksAccess: TasksAccess): PlanAccess {
	let draft: PlanDraft | null = null;
	let pendingImplementationHandoff: PendingImplementationHandoff | null = null;

	pi.on("agent_end", async (_event, ctx) => {
		if (!pendingImplementationHandoff) return;
		const handoff = pendingImplementationHandoff;
		pendingImplementationHandoff = null;

		// Pi clears isStreaming after awaited agent_end handlers finish; defer to the next macrotask.
		setTimeout(() => {
			let handoffSent = false;
			const sendHandoff = () => {
				if (handoffSent) return;
				handoffSent = true;
				pi.sendUserMessage(buildHandoffMessage(handoff.mode));
			};

			const usagePercent = ctx.getContextUsage()?.percent;
			const shouldCompact = typeof usagePercent === "number" && usagePercent > HANDOFF_COMPACTION_THRESHOLD_PERCENT;

			if (!shouldCompact) {
				sendHandoff();
				return;
			}

			try {
				ctx.compact({
					customInstructions: buildHandoffCompactionInstructions(handoff),
					onComplete: sendHandoff,
					onError: sendHandoff,
				});
			} catch {
				sendHandoff();
			}
		}, 0);
	});

	pi.registerTool({
		name: "plan",
		label: "Plan",
		description:
			"Submit a structured plan for user review. Blocks until the user approves or provides feedback. " +
			"On approval, creates the goal and tasks. Analysis plans stay in analysis mode; " +
			"implementation plans ask for supervisor vs IC/executor posture. " +
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

				if (getAgentMode() === "analysis") {
					tasksAccess.activateGoalCycle(draft.goal.content, approvedTasks, planRef, "analysis");

					const result = buildApprovedResult(draft, "analysis");
					draft = null;
					return {
						content: [{ type: "text", text: result }],
						details: undefined,
					};
				}

				const implementationMode = await selectImplementationMode(ctx);
				if (!implementationMode) {
					return {
						content: [
							{
								type: "text",
								text: JSON.stringify({
									status: "handoff_cancelled",
									next_step:
										"Plan approved, but an execution pathway was not selected. Seek user confirmation to begin implementation.",
								}),
							},
						],
						details: undefined,
					};
				}

				const workspace = getWorkspaceState();
				const activeWorktree = workspace?.activeWorktree ?? null;
				let worktree: HandoffWorktreeResult;
				if (
					activeWorktree &&
					shouldReuseActiveWorktreeForHandoff(resolveSessionProductRoleOverride(), activeWorktree)
				) {
					worktree = workspaceWorktreeToHandoffWorktree(activeWorktree);
				} else {
					const worktreeTarget = await selectWorktreeTarget(ctx, draft.goal.content, draft.worktreeSlug);
					if (!worktreeTarget) {
						return {
							content: [
								{
									type: "text",
									text: JSON.stringify({
										status: "handoff_cancelled",
										next_step:
											"Plan approved, but an execution worktree was not selected. Seek user confirmation before implementation.",
									}),
								},
							],
							details: undefined,
						};
					}

					try {
						worktree = workspaceWorktreeToHandoffWorktree(
							await activateWorkspaceWorktree(worktreeTarget.worktreeLabel, worktreeTarget.branchName),
						);
					} catch (err) {
						return {
							content: [{ type: "text", text: buildWorktreeActivationFailedResult(worktreeTarget.worktreeLabel, err) }],
							details: undefined,
						};
					}
				}

				setAgentMode(implementationMode);
				tasksAccess.activateGoalCycle(draft.goal.content, approvedTasks, planRef, implementationMode);
				pendingImplementationHandoff = buildPendingImplementationHandoff(draft, implementationMode, worktree);

				let setupSummary: WorktreeSetupSummary | undefined;
				const repo = requireWorkspaceState().repo;
				const setupCommand = repo?.name ? readWorktreeSetupCommand(repo.name) : null;
				if (shouldRunWorktreeSetup(worktree.created, setupCommand)) {
					const repoRoot = repo?.root;
					if (repoRoot) {
						ctx.ui.notify("Provisioning worktree — running setup (up to 3 min)…", "info");
						try {
							const setupResult = await runWorktreeSetup(pi, {
								command: setupCommand as string,
								worktreeDir: worktree.worktreeDir,
								repoRoot,
							});
							setupSummary = worktreeSetupSummary(setupResult);
							if (setupResult.timedOut) {
								ctx.ui.notify("Worktree setup timed out after 3 min — continuing to handoff.", "warning");
							} else if (setupResult.exitCode !== 0) {
								ctx.ui.notify(`Worktree setup exited ${setupResult.exitCode} — continuing to handoff.`, "warning");
							} else {
								ctx.ui.notify("Worktree setup complete.", "info");
							}
						} catch (err) {
							ctx.ui.notify(
								`Worktree setup error — continuing to handoff: ${err instanceof Error ? err.message : String(err)}`,
								"warning",
							);
						}
					}
				}

				const result = buildApprovedResult(draft, implementationMode, worktree, setupSummary);
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
					const approvedMode = parsed.implementation_mode ?? parsed.plan_mode;
					const mode = approvedMode ? ` → ${approvedMode}` : "";
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
	};
}
