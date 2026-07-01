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
 * Re-submissions diff against the previous draft — unchanged approved sections
 * keep their ✓ status, changed sections reset to ★ (needs re-review).
 */

import type { ExtensionAPI, ExtensionContext, Theme } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { readWorktreeSetupCommand } from "pi-core/platform/config.ts";
import {
	activateWorkspaceWorktree,
	getWorkspaceState,
	listWorkspaceWorktrees,
	requireWorkspaceState,
	type WorkspaceWorktree,
} from "pi-core/platform/workspace.ts";
import { getAgentMode, setAgentMode } from "pi-core/session/agent-mode.ts";
import { shortSessionId } from "pi-core/session/session-id.ts";
import { runWorktreeSetup, type WorktreeSetupResult } from "pi-core/workspace/setup.ts";
import { getOrCreateWorktree, type WorktreeResult } from "pi-core/workspace/worktree.ts";
import type { GoalCycle, ReviewState, TaskStatus, TasksAccess } from "../tasks/tasks";
import {
	computeCollectiveReview,
	computeGoalContextReview,
	computeSectionReview,
	tasksMatch,
	workstreamsMatch,
} from "./draft-logic.ts";
import { normalizePlanExecutionInput, type PlanTaskInput, type PlanWorkstreamInput } from "./plan-input.ts";
import type { PlanDraft, TaskPlanDraft, WorkstreamPlanDraft } from "./review.ts";
import { SECTION_NAMES, showPlanReadOnly, showReviewOverlay } from "./review.ts";
import {
	buildExecutionWorktreeChoices,
	CUSTOM_WORKTREE_CHOICE,
	customWorktreeTarget,
	type ExecutionWorktreeTarget,
	suggestWorktreeTarget,
} from "./worktree-choices.ts";
import { shouldRunWorktreeSetup, type WorktreeSetupSummary, worktreeSetupSummary } from "./worktree-setup.ts";

// ============================================================================
// Draft diffing — preserve approvals on unchanged content
// ============================================================================

interface DraftParams {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
}

function buildCommonDraftSections(params: DraftParams, previous: PlanDraft | null) {
	const goalContextState = computeGoalContextReview(
		params.goal,
		params.context,
		previous ? { goal: previous.goal, context: previous.context } : null,
	);

	return {
		goal: { content: params.goal, review: goalContextState },
		context: { content: params.context, review: goalContextState },
		design: { content: params.design, review: computeSectionReview(params.design, previous?.design ?? null) },
		success: { content: params.success, review: computeSectionReview(params.success, previous?.success ?? null) },
		boundaries: {
			content: params.boundaries,
			review: computeSectionReview(params.boundaries, previous?.boundaries ?? null),
		},
	};
}

function buildTaskDraft(
	params: DraftParams & { worktreeSlug?: string },
	tasks: PlanTaskInput[],
	previous: PlanDraft | null,
): TaskPlanDraft {
	const previousTaskDraft = previous?.executionKind === "tasks" ? previous : null;

	return {
		...buildCommonDraftSections(params, previous),
		executionKind: "tasks",
		worktreeSlug: params.worktreeSlug ?? null,
		tasks: tasks.map((t) => ({
			label: t.label,
			description: t.description,
			criteria: t.criteria,
			notes: null,
			status: "pending" as TaskStatus,
			review: null,
		})),
		tasksReview: computeCollectiveReview(
			previousTaskDraft ? tasksMatch(tasks, previousTaskDraft.tasks) : false,
			previousTaskDraft?.tasksReview ?? null,
		),
	};
}

function buildWorkstreamDraft(
	params: DraftParams,
	workstreams: PlanWorkstreamInput[],
	previous: PlanDraft | null,
): WorkstreamPlanDraft {
	const previousWorkstreamDraft = previous?.executionKind === "workstreams" ? previous : null;

	return {
		...buildCommonDraftSections(params, previous),
		executionKind: "workstreams",
		workstreams: workstreams.map((workstream) => ({
			...workstream,
			...(workstream.dependsOn !== undefined ? { dependsOn: [...workstream.dependsOn] } : {}),
		})),
		workstreamsReview: computeCollectiveReview(
			previousWorkstreamDraft ? workstreamsMatch(workstreams, previousWorkstreamDraft.workstreams) : false,
			previousWorkstreamDraft?.workstreamsReview ?? null,
		),
	};
}

// ============================================================================
// Review result builders
// ============================================================================

function getCollectiveReview(draft: PlanDraft): { key: "tasks" | "workstreams"; review: ReviewState } {
	if (draft.executionKind === "tasks") return { key: "tasks", review: draft.tasksReview };
	return { key: "workstreams", review: draft.workstreamsReview };
}

function isAllApproved(draft: PlanDraft): boolean {
	for (const name of SECTION_NAMES) {
		if (!draft[name].review.approved) return false;
	}
	if (!getCollectiveReview(draft).review.approved) return false;
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

	// Tasks/workstreams are reviewed collectively.
	const collective = getCollectiveReview(draft);
	approved[collective.key] = collective.review.approved;
	if (collective.review.feedback && !collective.review.approved) revisions[collective.key] = collective.review.feedback;
	if (collective.review.feedback && collective.review.approved) notes[collective.key] = collective.review.feedback;

	const result: Record<string, unknown> = {
		status: "feedback",
		approved,
		revisions,
	};

	if (draft.executionKind === "workstreams") result.plan_kind = "workstreams";

	// Include approved-with-notes so agent sees them alongside revisions
	if (Object.keys(notes).length > 0) result.notes = notes;

	return JSON.stringify(result);
}

function collectApprovedNotes(draft: PlanDraft): Record<string, string> {
	const notes: Record<string, string> = {};
	for (const name of SECTION_NAMES) {
		const r = draft[name].review;
		if (r.approved && r.feedback) notes[name] = r.feedback;
	}

	const collective = getCollectiveReview(draft);
	if (collective.review.approved && collective.review.feedback) {
		notes[collective.key] = collective.review.feedback;
	}

	return notes;
}

export type ImplementationMode = "supervisor" | "executor";
type ApprovedPlanMode = "analysis" | ImplementationMode;

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

type HandoffWorktreeResult = {
	worktreeDir: string;
	label: string;
	branch: string;
	created: boolean;
};

interface PendingImplementationHandoff {
	mode: ImplementationMode;
	worktree: HandoffWorktreeContext;
	plan: HandoffPlanContext;
}

const IMPLEMENTATION_MODE_CHOICES = ["Execute as Supervisor", "Execute as IC/executor"] as const;

async function selectImplementationMode(ctx: ExtensionContext): Promise<ImplementationMode | null> {
	if (!ctx.hasUI) return null;

	const choice = await ctx.ui.select("Execute approved plan as", [...IMPLEMENTATION_MODE_CHOICES]);
	if (choice === "Execute as Supervisor") return "supervisor";
	if (choice === "Execute as IC/executor") return "executor";
	return null;
}

async function selectWorktreeTarget(
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

const HANDOFF_COMPACTION_THRESHOLD_PERCENT = 30;

export function buildHandoffMessage(mode: ImplementationMode): string {
	if (mode === "supervisor") {
		return "Plan looks good — proceed as supervisor. Delegate bounded investigation and implementation to subagents; keep synthesis, decisions, and integration here.";
	}

	return "Plan looks good — proceed with direct implementation.";
}

function buildWorktreeActivationFailedResult(label: string, error: unknown): string {
	const message = error instanceof Error ? error.message : String(error);
	return JSON.stringify({
		status: "worktree_activation_failed",
		worktree_label: label,
		message,
		next_step: "Fix the protected checkout or choose another worktree, then resubmit the approved plan.",
	});
}

function buildApprovedResult(
	draft: TaskPlanDraft,
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

interface WorkstreamActivationDeps {
	getWorkspaceState(): ReturnType<typeof getWorkspaceState>;
	getOrCreateWorktree(
		pi: ExtensionAPI,
		repoRoot: string,
		repoName: string,
		label: string,
		branchName?: string | null,
	): Promise<WorktreeResult>;
	readWorktreeSetupCommand(repoName: string): string | null;
	runWorktreeSetup(
		pi: ExtensionAPI,
		opts: { command: string; worktreeDir: string; repoRoot: string },
	): Promise<WorktreeSetupResult>;
}

const DEFAULT_WORKSTREAM_ACTIVATION_DEPS: WorkstreamActivationDeps = {
	getWorkspaceState,
	getOrCreateWorktree,
	readWorktreeSetupCommand,
	runWorktreeSetup,
};

type WorkstreamProvisionStage = "worktree" | "setup";
type WorkstreamProvisionStatus = "activated" | "failed";

interface ApprovedWorkstreamEntry {
	id: string;
	label: string;
	scope: string;
	outcome: string;
	boundaries: string;
	worktreeSlug?: string;
	dependsOn: string[];
	status: "ready" | "blocked";
	activation_status?: WorkstreamProvisionStatus;
	failure_stage?: WorkstreamProvisionStage;
	message?: string;
	worktree?: {
		label: string;
		path: string;
		branch: string;
		created: boolean;
	};
	worktree_setup?: WorktreeSetupSummary;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function setupFailureMessage(summary: WorktreeSetupSummary): string {
	if (summary.timed_out) return "Worktree setup timed out.";
	return `Worktree setup exited ${summary.exit_code}.`;
}

export async function buildApprovedWorkstreamResult(
	pi: ExtensionAPI,
	draft: WorkstreamPlanDraft,
	ctx: ExtensionContext,
	deps: WorkstreamActivationDeps = DEFAULT_WORKSTREAM_ACTIVATION_DEPS,
): Promise<string> {
	const notes = collectApprovedNotes(draft);
	const workstreams: Record<string, ApprovedWorkstreamEntry> = {};
	const ready: string[] = [];
	const blocked: Record<string, string[]> = {};

	for (const workstream of draft.workstreams) {
		const dependsOn = workstream.dependsOn ?? [];
		const status = dependsOn.length === 0 ? "ready" : "blocked";
		workstreams[workstream.id] = {
			id: workstream.id,
			label: workstream.label,
			scope: workstream.scope,
			outcome: workstream.outcome,
			boundaries: workstream.boundaries,
			...(workstream.worktreeSlug !== undefined ? { worktreeSlug: workstream.worktreeSlug } : {}),
			dependsOn,
			status,
		};
		if (status === "ready") {
			ready.push(workstream.id);
		} else {
			blocked[workstream.id] = dependsOn;
		}
	}

	if (ready.length === 0) {
		const result: Record<string, unknown> = {
			status: "approved",
			plan_kind: "workstreams",
			goal: draft.goal.content,
			context: draft.context.content,
			design: draft.design.content,
			success: draft.success.content,
			boundaries: draft.boundaries.content,
			implementation_mode: "supervisor",
			handoff_status: "workstreams_blocked",
			next_step:
				"Workstream plan approved. No workstreams are ready because each workstream has dependencies; no worktrees were provisioned.",
			workstream_progress: {
				ready: 0,
				blocked: Object.keys(blocked).length,
				activated: 0,
				failed: 0,
				total: draft.workstreams.length,
			},
			workstream_graph: {
				ready,
				blocked,
			},
			workstreams,
		};

		if (Object.keys(notes).length > 0) result.notes = notes;
		return JSON.stringify(result);
	}

	const workspace = deps.getWorkspaceState();
	const repo = workspace?.repo;
	if (!repo) {
		for (const workstreamId of ready) {
			const entry = workstreams[workstreamId]!;
			entry.activation_status = "failed";
			entry.failure_stage = "worktree";
			entry.message = "Workstream activation requires an initialized git repository workspace.";
		}

		const result: Record<string, unknown> = {
			status: "handoff_cancelled",
			plan_kind: "workstreams",
			goal: draft.goal.content,
			context: draft.context.content,
			design: draft.design.content,
			success: draft.success.content,
			boundaries: draft.boundaries.content,
			implementation_mode: "supervisor",
			handoff_status: "workstream_activation_cancelled",
			message: "Workstream activation requires an initialized git repository workspace.",
			next_step:
				"Workstream plan approved, but ready workstreams were not activated because no repository workspace is available. Re-run from a repository-backed Basecamp session.",
			workstream_progress: {
				ready: ready.length,
				blocked: Object.keys(blocked).length,
				activated: 0,
				failed: ready.length,
				total: draft.workstreams.length,
			},
			workstream_graph: {
				ready,
				blocked,
			},
			workstreams,
		};

		if (Object.keys(notes).length > 0) result.notes = notes;
		return JSON.stringify(result);
	}

	const sessionTag = shortSessionId(ctx.sessionManager.getSessionId());
	const setupCommand = deps.readWorktreeSetupCommand(repo.name);
	const targetsByWorkstream = new Map<string, ExecutionWorktreeTarget>();
	const workstreamIdsByLabel = new Map<string, string[]>();

	for (const workstreamId of ready) {
		const workstream = draft.workstreams.find((candidate) => candidate.id === workstreamId)!;
		const target = suggestWorktreeTarget(workstream.label, workstream.worktreeSlug ?? workstream.id, sessionTag);
		targetsByWorkstream.set(workstreamId, target);
		workstreamIdsByLabel.set(target.worktreeLabel, [
			...(workstreamIdsByLabel.get(target.worktreeLabel) ?? []),
			workstreamId,
		]);
	}

	for (const [label, workstreamIds] of workstreamIdsByLabel) {
		if (workstreamIds.length <= 1) continue;
		for (const workstreamId of workstreamIds) {
			const entry = workstreams[workstreamId]!;
			entry.activation_status = "failed";
			entry.failure_stage = "worktree";
			entry.message = `Derived worktree label '${label}' is shared by ready workstreams: ${workstreamIds.join(", ")}.`;
		}
	}

	for (const workstreamId of ready) {
		const entry = workstreams[workstreamId]!;
		if (entry.activation_status === "failed") continue;
		const target = targetsByWorkstream.get(workstreamId)!;

		try {
			const worktree = await deps.getOrCreateWorktree(
				pi,
				repo.root,
				repo.name,
				target.worktreeLabel,
				target.branchName,
			);
			entry.activation_status = "activated";
			entry.worktree = {
				label: worktree.label,
				path: worktree.worktreeDir,
				branch: worktree.branch,
				created: worktree.created,
			};

			if (shouldRunWorktreeSetup(worktree.created, setupCommand)) {
				try {
					const setupResult = await deps.runWorktreeSetup(pi, {
						command: setupCommand as string,
						worktreeDir: worktree.worktreeDir,
						repoRoot: repo.root,
					});
					const setupSummary = worktreeSetupSummary(setupResult);
					if (setupSummary) {
						entry.worktree_setup = setupSummary;
						if (!setupSummary.ok) {
							entry.activation_status = "failed";
							entry.failure_stage = "setup";
							entry.message = setupFailureMessage(setupSummary);
						}
					}
				} catch (error) {
					entry.activation_status = "failed";
					entry.failure_stage = "setup";
					entry.message = errorMessage(error);
				}
			}
		} catch (error) {
			entry.activation_status = "failed";
			entry.failure_stage = "worktree";
			entry.message = errorMessage(error);
		}
	}

	const activatedCount = ready.filter((id) => workstreams[id]?.activation_status === "activated").length;
	const failedCount = ready.filter((id) => workstreams[id]?.activation_status === "failed").length;
	const result: Record<string, unknown> = {
		status: "approved",
		plan_kind: "workstreams",
		goal: draft.goal.content,
		context: draft.context.content,
		design: draft.design.content,
		success: draft.success.content,
		boundaries: draft.boundaries.content,
		implementation_mode: "supervisor",
		handoff_status: failedCount > 0 ? "workstreams_partially_activated" : "workstreams_activated",
		next_step:
			failedCount > 0
				? "Workstream plan approved. Ready workstream activation was attempted; inspect failed ready streams before launching agents. Do not launch agents yet; Task 4 handles launch."
				: "Workstream plan approved. Ready workstream worktrees are provisioned. Do not launch agents yet; Task 4 handles launch.",
		workstream_progress: {
			ready: ready.length,
			blocked: Object.keys(blocked).length,
			activated: activatedCount,
			failed: failedCount,
			total: draft.workstreams.length,
		},
		workstream_graph: {
			ready,
			blocked,
		},
		workstreams,
	};

	if (Object.keys(notes).length > 0) result.notes = notes;

	return JSON.stringify(result);
}

function buildPendingImplementationHandoff(
	draft: TaskPlanDraft,
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

function buildHandoffCompactionInstructions(handoff: PendingImplementationHandoff): string {
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

// ============================================================================
// Tool render helpers
// ============================================================================

function renderSuccess(message: string, theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("success", "✓") + theme.fg("dim", ` ${message}`), 0, 0);
}

function renderPartial(theme: Theme) {
	const { Text } = require("@earendil-works/pi-tui");
	return new Text(theme.fg("dim", "..."), 0, 0);
}

// ============================================================================
// Types (exported)
// ============================================================================

export interface PlanAccess {
	getDraft(): PlanDraft | null;
}

function workspaceWorktreeToHandoffWorktree(target: WorkspaceWorktree): HandoffWorktreeResult {
	return {
		worktreeDir: target.path,
		label: target.label,
		branch: target.branch ?? "detached",
		created: target.created,
	};
}

// ============================================================================
// Registration
// ============================================================================

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
			tasks: Type.Optional(
				Type.Array(
					Type.Object({
						label: Type.String({ description: "Short task name" }),
						description: Type.String({ description: "What this task involves and why" }),
						criteria: Type.String({ description: "What done looks like for this task" }),
					}),
					{ description: "Ordered list of tasks. Mutually exclusive with workstreams.", minItems: 1 },
				),
			),
			workstreams: Type.Optional(
				Type.Array(
					Type.Object({
						id: Type.String({ description: "Stable workstream id used by dependsOn references" }),
						label: Type.String({ description: "Short workstream name" }),
						scope: Type.String({ description: "What this workstream includes" }),
						outcome: Type.String({ description: "Expected result of this workstream" }),
						boundaries: Type.String({ description: "What is out of scope for this workstream" }),
						worktreeSlug: Type.Optional(
							Type.String({
								description:
									"Internal metadata for worktree label suggestion; short kebab-case slug, no session prefix.",
							}),
						),
						dependsOn: Type.Optional(
							Type.Array(Type.String({ description: "Workstream id this workstream depends on" }), {
								description: "Workstream ids that must complete first",
							}),
						),
					}),
					{ description: "Ordered list of workstreams. Mutually exclusive with tasks.", minItems: 1 },
				),
			),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const executionInput = normalizePlanExecutionInput(params);
			const draftParams = {
				goal: params.goal,
				context: params.context,
				design: params.design,
				success: params.success,
				boundaries: params.boundaries,
			};

			if (executionInput.kind === "tasks") {
				draft = buildTaskDraft(
					{
						...draftParams,
						worktreeSlug:
							params.worktreeSlug ?? (draft?.executionKind === "tasks" ? draft.worktreeSlug : undefined) ?? undefined,
					},
					executionInput.tasks,
					draft,
				);
			} else {
				draft = buildWorkstreamDraft(draftParams, executionInput.workstreams, draft);
			}

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
				if (draft.executionKind === "workstreams") {
					const result = await buildApprovedWorkstreamResult(pi, draft, ctx);
					draft = null;
					return {
						content: [{ type: "text", text: result }],
						details: undefined,
					};
				}

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

				let worktree: HandoffWorktreeResult;
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
			const workstreamCount = (args.workstreams as unknown[])?.length ?? 0;
			const itemSummary = workstreamCount > 0 ? `${workstreamCount} workstreams` : `${taskCount} tasks`;
			return new Text(
				theme.fg("toolTitle", theme.bold("plan ")) + theme.fg("dim", `${preview} (${itemSummary})`),
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

// ============================================================================
// /show-plan command — view or re-review plan
// ============================================================================

export function registerPlanCommands(pi: ExtensionAPI, tasksAccess: TasksAccess, plan: PlanAccess): void {
	pi.registerCommand("plan", {
		description: "Explore a topic and formalise an execution plan",
		handler: async (args, ctx) => {
			const topic = args?.trim() || (ctx.hasUI ? await ctx.ui.input("What do you want to explore?") : undefined);
			if (!topic) {
				ctx.ui.notify("Usage: /plan <topic>", "error");
				return;
			}
			pi.sendUserMessage(
				`I want to explore and plan: ${topic}\n\nInvoke the \`planning\` skill. Do not jump straight to \`plan()\` — explore the problem space first, discuss the approach with me, then formalise the agreed execution plan. Do not prototype or edit code before the plan is approved.`,
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
