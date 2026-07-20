/**
 * Tasks — persistent goal/task tracking with a below-editor widget.
 *
 * Tracks a goal and an ordered task list with three states:
 *   ✓ completed  →  active  ·  pending
 *
 * Each task has a label, description, and criteria.
 *
 * Goal-cycle operations live in goal-cycle.ts, task-state text builders in
 * text.ts, file persistence in store.ts, and the widget in widget.ts. This
 * module owns the shared TasksRuntime and publishes a read-only TasksReader
 * (reader.ts) for cross-domain observers; the task tools and tool_call guards
 * are the tools/ layer, wired by the composition root.
 *
 * Widget shows a sliding window of 3 open tasks with collapse
 * counters for completed/remaining items.
 *
 * State is persisted to ~/.pi/basecamp/tasks/<session-id>.json.
 * Each file contains an array of goal cycles — at most one active.
 * Goal transitions archive the previous cycle and start a new one.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { setAgentMode } from "#core/agent-mode/index.ts";
import { getCurrentSessionState } from "#core/session/state/index.ts";
import type { GoalCycle, TasksState } from "../schemas/task.ts";
import { registerTasksReader } from "./reader.ts";
import { loadCycles, saveCycles, tasksFilePath } from "./store.ts";
import { buildSteerContent } from "./text.ts";
import { renderTaskWidgetLines } from "./widget.ts";

export { defaultTasksDir, tasksFilePath } from "./store.ts";

/** Shared mutable session state threaded through the lifecycle files. */
export interface TasksRuntime {
	state: TasksState;
	cycles: GoalCycle[];
	guardBlockCount: number;
	updateWidget(): void;
	persistState(): void;
}

export function registerTasks(pi: ExtensionAPI): TasksRuntime {
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

	registerTasksReader({ getState: () => runtime.state });
	return runtime;
}
