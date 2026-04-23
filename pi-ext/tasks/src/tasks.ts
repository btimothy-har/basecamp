/**
 * Tasks — persistent goal/task tracking with a below-editor widget.
 *
 * Tracks a goal and an ordered task list with three states:
 *   ✓ completed  →  active  ·  pending
 *
 * Each task has a label, description, and optional notes.
 * Description is set by the agent at creation. Notes are co-written
 * by the agent (via annotate_task) and the user (via /tasks command).
 *
 * Tools:
 *   - update_goal: set or change the session goal
 *   - create_tasks: set the ordered task list (replaces existing)
 *   - start_task: mark a task as active (returns task context)
 *   - complete_task: mark a task as done (optional notes)
 *   - get_task: read task context (description, notes)
 *   - annotate_task: set notes on a task
 *
 * Widget shows a sliding window of 3 open tasks with collapse
 * counters for completed/remaining items.
 *
 * State is persisted to ~/.pi/tasks/<session-id>.json.
 * Each file contains an array of goal cycles — at most one active.
 * Goal transitions archive the previous cycle and start a new one.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI, ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { visibleWidth, wrapTextWithAnsi } from "@mariozechner/pi-tui";
import { Type } from "@sinclair/typebox";

// ============================================================================
// Types
// ============================================================================

export type TaskStatus = "pending" | "active" | "completed" | "deleted";

export interface ReviewState {
	approved: boolean | null; // true = approved, false = revise, null = pending
	feedback: string | null;
}

export interface Task {
	label: string;
	description: string;
	criteria: string;
	notes: string | null;
	status: TaskStatus;
	review: ReviewState | null;
}

export interface TasksState {
	goal: string | null;
	tasks: Task[];
}

export interface GoalCycle {
	goal: string;
	tasks: Task[];
	planRef: {
		context: string;
		design: string;
		success: string;
		boundaries: string;
	} | null;
	active: boolean;
	archivedAt: string | null;
}

/** Exposed to /tasks command and /plan for state access + mutation. */
export interface TasksAccess {
	getState(): Readonly<TasksState>;
	setNotes(index: number, notes: string): void;
	/** Create a new goal cycle, archiving any active one. Sets state + persists. */
	activateGoalCycle(goal: string, tasks: Task[], planRef: GoalCycle["planRef"]): void;
	/** Get the active GoalCycle's planRef, if any. */
	getPlanRef(): GoalCycle["planRef"];
	/** Get the current ExtensionContext (null before session_start). */
	getContext(): ExtensionContext | null;
}

// ============================================================================
// State helpers
// ============================================================================

function requireTasks(state: TasksState, index: number): Task {
	if (state.tasks.length === 0) throw new Error("No tasks exist. Use create_tasks first.");
	if (!Number.isInteger(index) || index < 0 || index >= state.tasks.length) {
		throw new Error(`Invalid task index ${index}. Valid range: 0–${state.tasks.length - 1}.`);
	}
	return state.tasks[index]!;
}

// ============================================================================
// Widget Rendering
// ============================================================================

const WINDOW_SIZE = 3;

function renderWidget(
	state: TasksState,
	fg: (color: Parameters<Theme["fg"]>[0], text: string) => string,
	_bold: Theme["bold"],
	width: number,
): string[] {
	const hasContent = state.goal || state.tasks.length > 0;
	if (!hasContent) return [];

	const inner: string[] = [];
	const boxWidth = width;

	if (state.goal) {
		inner.push(`${fg("dim", "Goal")}  ${state.goal}`);
	}

	if (state.tasks.length > 0) {
		const completedCount = state.tasks.filter((t) => t.status === "completed").length;
		const deletedCount = state.tasks.filter((t) => t.status === "deleted").length;

		// Find window start: first active task, or first pending if none active
		const activeIdx = state.tasks.findIndex((t) => t.status === "active");
		const firstPendingIdx = state.tasks.findIndex((t) => t.status === "pending");
		const windowStart = activeIdx >= 0 ? activeIdx : firstPendingIdx >= 0 ? firstPendingIdx : state.tasks.length;

		// Window: up to WINDOW_SIZE tasks from windowStart (skip completed)
		const windowTasks: Task[] = [];
		for (let i = windowStart; i < state.tasks.length && windowTasks.length < WINDOW_SIZE; i++) {
			const task = state.tasks[i];
			if (task && task.status !== "completed") {
				windowTasks.push(task);
			}
		}

		// Remaining pending tasks after the window
		const pendingInWindow = windowTasks.filter((t) => t.status === "pending").length;
		const totalPending = state.tasks.filter((t) => t.status === "pending").length;
		const remainingCount = totalPending - pendingInWindow;

		if (state.goal) {
			inner.push("");
		}

		// Header: collapsed counts
		const counts: string[] = [];
		if (completedCount > 0) counts.push(`+${completedCount} completed`);
		if (deletedCount > 0) counts.push(`+${deletedCount} deleted`);
		if (counts.length > 0) {
			inner.push(fg("muted", `(${counts.join(", ")})`));
		}

		// Window
		for (const task of windowTasks) {
			const notesMark = task.notes ? fg("dim", " 📝") : "";
			if (task.status === "deleted") {
				inner.push(`${fg("dim", "✕")} ${fg("dim", task.label)}`);
			} else if (task.status === "active") {
				inner.push(`${fg("accent", "→")} ${fg("accent", task.label)}${notesMark}`);
				inner.push(`  ${fg("dim", task.description)}`);
			} else {
				inner.push(`${fg("muted", "☐")} ${task.label}${notesMark}`);
			}
		}

		// Footer: remaining
		if (remainingCount > 0) {
			inner.push(fg("muted", `(+${remainingCount} to do)`));
		}
	}

	// Box-draw border
	const contentWidth = boxWidth - 4;
	const top = fg("dim", `╭${"─".repeat(boxWidth - 2)}╮`);
	const bottom = fg("dim", `╰${"─".repeat(boxWidth - 2)}╯`);
	const lines: string[] = [top];
	for (const line of inner) {
		const wrapped = wrapTextWithAnsi(line, contentWidth);
		for (const wl of wrapped) {
			const vw = visibleWidth(wl);
			const pad = Math.max(0, contentWidth - vw);
			lines.push(`${fg("dim", "│")} ${wl}${" ".repeat(pad)} ${fg("dim", "│")}`);
		}
	}
	lines.push(bottom);
	return lines;
}

// ============================================================================
// Steer message
// ============================================================================

function buildSteerContent(state: TasksState, planRef: GoalCycle["planRef"]): string | null {
	if (!state.goal) return null;

	const lines = [`Current progress:`, `Goal: ${state.goal}`];

	// Include plan context for drift prevention
	if (planRef) {
		lines.push("");
		lines.push(`Design: ${planRef.design}`);
		lines.push(`Boundaries: ${planRef.boundaries}`);
	}

	if (state.tasks.length > 0) {
		const live = state.tasks.filter((t) => t.status !== "deleted");
		const completedCount = live.filter((t) => t.status === "completed").length;
		lines.push("");
		lines.push(`Completed: ${completedCount}/${live.length}`);
		lines.push("");

		const markers: Record<TaskStatus, string> = { completed: "✓", active: "→", pending: "☐", deleted: "✕" };
		for (let i = 0; i < state.tasks.length; i++) {
			const t = state.tasks[i]!;
			if (t.status === "deleted") continue;
			lines.push(`  [${i}] ${markers[t.status]} ${t.label}`);
			if (t.status !== "completed" && t.notes) {
				lines.push(`       Notes: ${t.notes}`);
			}
		}
	}

	lines.push(
		"",
		"Call start_task before beginning work on a task. Call complete_task when done. If the plan changes, call create_tasks with the updated list.",
		"",
		"Do not jump straight into execution. First use `discover` to inspect relevant tools, skills, and agents. Load the needed skill with `skill({ name })`. Delegate bounded work with `agent({ task })` before doing it yourself.",
	);
	return lines.join("\n");
}

// ============================================================================
// State snapshot for tool results
// ============================================================================

function buildProgress(state: TasksState): { completed: number; deleted: number; total: number } {
	const deleted = state.tasks.filter((t) => t.status === "deleted").length;
	const live = state.tasks.length - deleted;
	const completed = state.tasks.filter((t) => t.status === "completed").length;
	return { completed, deleted, total: live };
}

function buildStateSnapshot(state: TasksState): string {
	const tasks: Record<string, { label: string; status: string }> = {};
	for (let i = 0; i < state.tasks.length; i++) {
		const t = state.tasks[i]!;
		if (t.status === "deleted") continue;
		tasks[i] = { label: t.label, status: t.status };
	}

	return JSON.stringify({
		goal: state.goal,
		progress: buildProgress(state),
		tasks,
	});
}

function buildTaskContext(task: Task, index: number, state: TasksState): string {
	return JSON.stringify({
		index,
		label: task.label,
		status: task.status,
		description: task.description,
		criteria: task.criteria,
		notes: task.notes,
		progress: buildProgress(state),
	});
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
// File persistence — ~/.pi/tasks/<session-id>.json
// ============================================================================

const TASKS_DIR = path.join(os.homedir(), ".pi", "tasks");

function loadCycles(filePath: string): GoalCycle[] {
	try {
		const raw = fs.readFileSync(filePath, "utf8");
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

function saveCycles(filePath: string, cycles: GoalCycle[]): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(cycles, null, 2));
	fs.renameSync(tmp, filePath);
}

// ============================================================================
// Registration
// ============================================================================

const TASK_TOOLS = new Set([
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"get_task",
	"annotate_task",
	"delete_task",
	"escalate",
	"plan",
	"discover",
	"skill",
	"read",
]);
const GATED_WITHOUT_TASKS = new Set(["edit", "write"]);

export function registerTasks(pi: ExtensionAPI): TasksAccess {
	let ctx: ExtensionContext | null = null;
	let state: TasksState = { goal: null, tasks: [] };
	let cycles: GoalCycle[] = [];
	let taskFilePath: string | null = null;
	let guardBlockCount = 0;

	function updateWidget(): void {
		if (!ctx?.hasUI) return;

		const hasContent = state.goal || state.tasks.length > 0;
		if (!hasContent) {
			ctx.ui.setWidget("basecamp-tasks", undefined, { placement: "belowEditor" });
			return;
		}

		ctx.ui.setWidget(
			"basecamp-tasks",
			(_tui, theme) => {
				const fg = theme.fg.bind(theme);
				const bold = theme.bold.bind(theme);
				let cachedLines: string[] | null = null;
				let cachedWidth = 0;

				return {
					invalidate() {
						cachedLines = null;
					},
					render(width: number): string[] {
						if (cachedLines && cachedWidth === width) return cachedLines;
						cachedWidth = width;
						cachedLines = renderWidget(state, fg, bold, width);
						return cachedLines;
					},
				};
			},
			{ placement: "belowEditor" },
		);
	}

	function persistState(): void {
		// Sync in-memory state back to the active cycle
		const active = cycles.find((c) => c.active);
		if (active) {
			active.tasks = state.tasks;
		}

		if (taskFilePath) {
			saveCycles(taskFilePath, cycles);
		}
	}

	// --- Task guardrails ---
	pi.on("tool_call", async (event) => {
		if (TASK_TOOLS.has(event.toolName)) return;

		let reason: string | null = null;
		if (!state.goal) {
			reason = "Set a goal with update_goal before proceeding.";
		} else if (GATED_WITHOUT_TASKS.has(event.toolName)) {
			const hasOpenTasks = state.tasks.some((t) => t.status === "pending" || t.status === "active");
			if (!hasOpenTasks) {
				reason = "Break work into tasks with create_tasks before editing files.";
			}
		}

		if (!reason) return;

		// First violation: hard block. Subsequent: soft steer.
		if (guardBlockCount === 0) {
			guardBlockCount++;
			return { block: true, reason };
		}

		guardBlockCount++;
		pi.sendMessage({ customType: "tasks-guard", content: reason, display: false }, { deliverAs: "steer" });
	});

	// --- Tool: update_goal ---
	pi.registerTool({
		name: "update_goal",
		label: "Update Goal",
		description: "Set or change the session goal. Call at the start of any task to establish what success looks like.",
		promptSnippet: "Set the session goal",
		parameters: Type.Object({
			goal: Type.String({ description: "What success looks like — concrete and verifiable (1 sentence)" }),
		}),
		async execute(_id, params) {
			// Archive the current goal cycle if one exists
			const active = cycles.find((c) => c.active);
			if (active) {
				active.tasks = state.tasks;
				active.active = false;
				active.archivedAt = new Date().toISOString();
			}

			// Start a new cycle
			cycles.push({ goal: params.goal, tasks: [], planRef: null, active: true, archivedAt: null });
			state.goal = params.goal;
			state.tasks = [];
			guardBlockCount = 0;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const goal = (args.goal as string) || "...";
			const preview = goal.length > 60 ? `${goal.slice(0, 60)}...` : goal;
			return new Text(theme.fg("toolTitle", theme.bold("update_goal ")) + theme.fg("dim", preview), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("goal updated", theme);
		},
	});

	// --- Tool: create_tasks ---
	pi.registerTool({
		name: "create_tasks",
		label: "Create Tasks",
		description:
			"Set the ordered task list for the current goal. Replaces any existing tasks. Requires a goal to be set first.",
		promptSnippet: "Set the task list for the current goal",
		parameters: Type.Object({
			tasks: Type.Array(
				Type.Object({
					label: Type.String({ description: "Short task name" }),
					description: Type.String({ description: "What this task involves and why" }),
					criteria: Type.String({ description: "What done looks like for this task" }),
				}),
				{ description: "Ordered list of tasks" },
			),
		}),
		async execute(_id, params) {
			if (!state.goal) {
				throw new Error("Cannot create tasks without a goal. Call update_goal first.");
			}
			state.tasks = params.tasks.map((t) => ({
				label: t.label,
				description: t.description,
				criteria: t.criteria,
				notes: null,
				status: "pending" as TaskStatus,
				review: null,
			}));
			guardBlockCount = 0;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const tasks = args.tasks as { label: string }[] | undefined;
			const count = tasks?.length ?? 0;
			return new Text(theme.fg("toolTitle", theme.bold("create_tasks ")) + theme.fg("dim", `${count} tasks`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess(`${state.tasks.length} tasks created`, theme);
		},
	});

	// --- Tool: start_task ---
	pi.registerTool({
		name: "start_task",
		label: "Start Task",
		description: "Mark a task as active by index. Only one task can be active at a time.",
		promptSnippet: "Mark a task as active",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);

			if (target.status === "completed" || target.status === "deleted") {
				throw new Error(`Task ${params.task} is ${target.status}.`);
			}

			// Clear any previously active task back to pending
			for (const t of state.tasks) {
				if (t.status === "active") t.status = "pending";
			}
			target.status = "active";
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildTaskContext(target, params.task, state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("start_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task started", theme);
		},
	});

	// --- Tool: complete_task ---
	pi.registerTool({
		name: "complete_task",
		label: "Complete Task",
		description: "Mark a task as completed by index.",
		promptSnippet: "Mark a task as completed",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);

			if (target.status === "completed" || target.status === "deleted") {
				throw new Error(`Task ${params.task} is ${target.status}.`);
			}

			target.status = "completed";
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(
				theme.fg("toolTitle", theme.bold("complete_task ")) + theme.fg("dim", `[${idx}] ${preview}`),
				0,
				0,
			);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task completed", theme);
		},
	});

	// --- Tool: get_task ---
	pi.registerTool({
		name: "get_task",
		label: "Get Task",
		description: "Read full task context by index — label, description, notes, and status.",
		promptSnippet: "Read task context",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);
			return {
				content: [{ type: "text", text: buildTaskContext(target, params.task, state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("get_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task loaded", theme);
		},
	});

	// --- Tool: annotate_task ---
	pi.registerTool({
		name: "annotate_task",
		label: "Annotate Task",
		description: "Set notes on a task. Replaces any existing notes.",
		promptSnippet: "Set notes on a task",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
			notes: Type.String({ description: "Free-text notes — context, decisions, blockers, relevant files" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);
			target.notes = params.notes;
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildTaskContext(target, params.task, state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(
				theme.fg("toolTitle", theme.bold("annotate_task ")) + theme.fg("dim", `[${idx}] ${preview}`),
				0,
				0,
			);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("notes updated", theme);
		},
	});

	// --- Tool: delete_task ---
	pi.registerTool({
		name: "delete_task",
		label: "Delete Task",
		description:
			"Mark a task as deleted by index. The task remains in the list (indices are stable) but is excluded from progress and execution.",
		promptSnippet: "Mark a task as deleted",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(state, params.task);

			if (target.status === "deleted") {
				throw new Error(`Task ${params.task} is already deleted.`);
			}

			// If deleting the active task, no need to reassign
			target.status = "deleted";
			updateWidget();
			persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@mariozechner/pi-tui");
			const idx = args.task as number;
			const label = state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("delete_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task deleted", theme);
		},
	});

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		state = { goal: null, tasks: [] };

		// Load from JSON file
		const sessionId = sessionCtx.sessionManager.getSessionId();
		taskFilePath = path.join(TASKS_DIR, `${sessionId}.json`);
		cycles = loadCycles(taskFilePath);

		const active = cycles.find((c) => c.active);
		if (active) {
			state.goal = active.goal;
			state.tasks = active.tasks;
		}

		updateWidget();
	});

	// --- before_agent_start: inject progress reminder ---
	pi.on("before_agent_start", async (_event, agentCtx) => {
		if (!agentCtx.hasUI) return;

		const activeCycle = cycles.find((c) => c.active);
		const content = buildSteerContent(state, activeCycle?.planRef ?? null);
		if (content) {
			pi.sendMessage(
				{
					customType: "tasks-context",
					content,
					display: false,
				},
				{ deliverAs: "steer" },
			);
		}
	});

	// --- Cleanup ---
	pi.on("session_shutdown", async () => {
		ctx = null;
	});

	return {
		getState: () => state,
		setNotes(index: number, notes: string) {
			const target = requireTasks(state, index);
			target.notes = notes;
			updateWidget();
			persistState();
		},
		activateGoalCycle(goal: string, tasks: Task[], planRef: GoalCycle["planRef"]) {
			const active = cycles.find((c) => c.active);
			if (active) {
				active.tasks = state.tasks;
				active.active = false;
				active.archivedAt = new Date().toISOString();
			}
			cycles.push({ goal, tasks, planRef, active: true, archivedAt: null });
			state.goal = goal;
			state.tasks = tasks;
			guardBlockCount = 0;
			updateWidget();
			persistState();
		},
		getPlanRef() {
			const active = cycles.find((c) => c.active);
			return active?.planRef ?? null;
		},
		getContext: () => ctx,
	};
}
