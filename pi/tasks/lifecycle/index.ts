/**
 * Tasks — persistent goal/task tracking with a below-editor widget.
 *
 * Tracks a goal and an ordered task list with three states:
 *   ✓ completed  →  active  ·  pending
 *
 * Each task has a label, description, and optional notes.
 * Description is set by the agent at creation. Notes are set by the
 * agent via annotate_task.
 *
 * The seven task tools live in tools.ts, the tool_call guardrails in
 * gate.ts, pure text builders in context.ts, and file persistence in
 * store.ts. This module owns the shared TasksRuntime and composes them.
 *
 * Widget shows a sliding window of 3 open tasks with collapse
 * counters for completed/remaining items.
 *
 * State is persisted to ~/.pi/basecamp/tasks/<session-id>.json.
 * Each file contains an array of goal cycles — at most one active.
 * Goal transitions archive the previous cycle and start a new one.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type AgentMode, setAgentMode } from "#core/agent-mode/index.ts";
import { getCurrentSessionState } from "#core/session/state/index.ts";
import { registerTasksAccess } from "./access.ts";
import { buildSteerContent, requireTasks } from "./context.ts";
import { registerTaskGuards } from "./gate.ts";
import { loadCycles, saveCycles, tasksFilePath } from "./store.ts";
import { registerTaskTools } from "./tools.ts";
import { renderTaskWidgetLines } from "./widget.ts";

// Type contracts owned by the tasks context — re-exported for the planning files.
export type { GoalCycle, ReviewState, Task, TaskStatus, TasksState } from "../schemas/task.ts";
export type { TasksAccess } from "./access.ts";
export { defaultTasksDir, tasksFilePath } from "./store.ts";

// Import the types we use locally.
import type { GoalCycle, Task, TasksState } from "../schemas/task.ts";
import type { TasksAccess } from "./access.ts";

/** Shared mutable session state threaded through gate.ts and tools.ts. */
export interface TasksRuntime {
	state: TasksState;
	cycles: GoalCycle[];
	guardBlockCount: number;
	updateWidget(): void;
	persistState(): void;
}

export function registerTasks(pi: ExtensionAPI): TasksAccess {
	let ctx: ExtensionContext | null = null;
	let taskFilePath: string | null = null;

	const runtime: TasksRuntime = {
		state: { goal: null, tasks: [] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget(): void {
			if (!ctx?.hasUI) return;

			const hasContent = runtime.state.goal || runtime.state.tasks.length > 0;
			if (!hasContent) {
				ctx.ui.setWidget("basecamp-tasks", undefined, { placement: "belowEditor" });
				return;
			}

			ctx.ui.setWidget(
				"basecamp-tasks",
				(_tui, theme) => {
					const fg = theme.fg.bind(theme);
					let cachedLines: string[] | null = null;
					let cachedWidth = 0;

					return {
						invalidate() {
							cachedLines = null;
						},
						render(width: number): string[] {
							if (cachedLines && cachedWidth === width) return cachedLines;
							cachedWidth = width;
							cachedLines = renderTaskWidgetLines(runtime.state, { fg }, width);
							return cachedLines;
						},
					};
				},
				{ placement: "belowEditor" },
			);
		},
		persistState(): void {
			// Sync in-memory state back to the active cycle
			const active = runtime.cycles.find((c) => c.active);
			if (active) {
				active.tasks = runtime.state.tasks;
			}

			if (taskFilePath) {
				saveCycles(taskFilePath, runtime.cycles);
			}
		},
	};

	registerTaskGuards(pi, runtime);
	registerTaskTools(pi, runtime);

	// --- Restore state on session start ---
	pi.on("session_start", async (_event, sessionCtx) => {
		ctx = sessionCtx;
		runtime.state = { goal: null, tasks: [] };

		// Load from JSON file
		const sessionId = sessionCtx.sessionManager.getSessionId();
		taskFilePath = tasksFilePath(sessionId);
		runtime.cycles = loadCycles(taskFilePath);

		const active = runtime.cycles.find((c) => c.active);
		if (active) {
			runtime.state.goal = active.goal;
			runtime.state.tasks = active.tasks;
			// Core's session_start (registered first) already initialized state.
			if (!getCurrentSessionState().agentMode && active.agentMode) setAgentMode(active.agentMode);
		}

		runtime.updateWidget();
	});

	// --- before_agent_start: inject progress reminder ---
	pi.on("before_agent_start", async (_event, agentCtx) => {
		if (!agentCtx.hasUI) return;

		const activeCycle = runtime.cycles.find((c) => c.active);
		const content = buildSteerContent(runtime.state, activeCycle?.planRef ?? null);
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

	const access: TasksAccess = {
		getState: () => runtime.state,
		setNotes(index: number, notes: string) {
			const target = requireTasks(runtime.state, index);
			target.notes = notes;
			runtime.updateWidget();
			runtime.persistState();
		},
		activateGoalCycle(goal: string, tasks: Task[], planRef: GoalCycle["planRef"], agentMode: AgentMode | null) {
			const active = runtime.cycles.find((c) => c.active);
			if (active) {
				active.tasks = runtime.state.tasks;
				active.active = false;
				active.archivedAt = new Date().toISOString();
			}
			runtime.cycles.push({ goal, tasks, planRef, agentMode, active: true, archivedAt: null });
			runtime.state.goal = goal;
			runtime.state.tasks = tasks;
			runtime.guardBlockCount = 0;
			runtime.updateWidget();
			runtime.persistState();
		},
		getPlanRef() {
			const active = runtime.cycles.find((c) => c.active);
			return active?.planRef ?? null;
		},
		getContext: () => ctx,
	};

	registerTasksAccess(access);
	return access;
}
