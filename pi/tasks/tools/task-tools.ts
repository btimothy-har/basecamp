/** The six task tools: update_goal, create_tasks, start_task, complete_task, get_task, delete_task. */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { getAgentMode } from "#core/agent-mode/index.ts";
import { startGoalCycle } from "../lifecycle/goal-cycle.ts";
import type { TasksRuntime } from "../lifecycle/index.ts";
import {
	buildCompleteTaskResultText,
	buildCompleteTaskStopMessage,
	buildProgress,
	buildStateSnapshot,
	buildTaskContext,
	type CompleteTaskResultDetails,
	isCompleteTaskStopWorkDetails,
	requireTasks,
} from "../lifecycle/text.ts";
import type { TaskStatus } from "../schemas/task.ts";
import { renderPartial, renderSuccess } from "./render.ts";

export function registerTaskTools(pi: ExtensionAPI, runtime: TasksRuntime): void {
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
			startGoalCycle(runtime, { goal: params.goal, tasks: [], planRef: null, agentMode: getAgentMode() });
			return {
				content: [{ type: "text", text: buildStateSnapshot(runtime.state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
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
			if (!runtime.state.goal) {
				throw new Error("Cannot create tasks without a goal. Call update_goal first.");
			}
			runtime.state.tasks = params.tasks.map((t) => ({
				label: t.label,
				description: t.description,
				criteria: t.criteria,
				status: "pending" as TaskStatus,
				review: null,
			}));
			runtime.guardBlockCount = 0;
			runtime.updateWidget();
			runtime.persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(runtime.state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
			const tasks = args.tasks as { label: string }[] | undefined;
			const count = tasks?.length ?? 0;
			return new Text(theme.fg("toolTitle", theme.bold("create_tasks ")) + theme.fg("dim", `${count} tasks`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess(`${runtime.state.tasks.length} tasks created`, theme);
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
			const target = requireTasks(runtime.state, params.task);

			if (target.status === "completed" || target.status === "deleted") {
				throw new Error(`Task ${params.task} is ${target.status}.`);
			}

			// Clear any previously active task back to pending
			for (const t of runtime.state.tasks) {
				if (t.status === "active") t.status = "pending";
			}
			target.status = "active";
			runtime.updateWidget();
			runtime.persistState();
			return {
				content: [{ type: "text", text: buildTaskContext(target, params.task, runtime.state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
			const idx = args.task as number;
			const label = runtime.state.tasks[idx]?.label ?? "...";
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
		description:
			"Mark a task as completed by index. Set stop_work to true only when this completion should end the agent loop because the task is done and this is a natural handoff. If stop_work is true, call complete_task as the only tool call in that assistant response; do not batch it with any other tool call.",
		promptSnippet: "Mark a task as completed, optionally stopping work",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
			stop_work: Type.Optional(
				Type.Boolean({
					description:
						"Set true when completing this task should stop the agent loop at a natural handoff. When true, complete_task must be the only tool call in that assistant response.",
				}),
			),
		}),
		async execute(_id, params) {
			const target = requireTasks(runtime.state, params.task);

			if (target.status === "completed" || target.status === "deleted") {
				throw new Error(`Task ${params.task} is ${target.status}.`);
			}

			const stopWork = params.stop_work === true;
			const stopMessage = stopWork ? buildCompleteTaskStopMessage(params.task, target) : null;
			target.status = "completed";
			runtime.updateWidget();
			runtime.persistState();
			return {
				content: [{ type: "text", text: buildCompleteTaskResultText(runtime.state, params.task, target, stopMessage) }],
				details: {
					task: params.task,
					label: target.label,
					stop_work: stopWork,
					stop_message: stopMessage,
					progress: buildProgress(runtime.state),
				} satisfies CompleteTaskResultDetails,
				terminate: stopWork,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
			const idx = args.task as number;
			const label = runtime.state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(
				theme.fg("toolTitle", theme.bold("complete_task ")) + theme.fg("dim", `[${idx}] ${preview}`),
				0,
				0,
			);
		},
		renderResult(result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			if (isCompleteTaskStopWorkDetails(result.details)) return renderSuccess("task completed — stopping", theme);
			return renderSuccess("task completed", theme);
		},
	});

	// --- Tool: get_task ---
	pi.registerTool({
		name: "get_task",
		label: "Get Task",
		description: "Read full task context by index — label, description, criteria, and status.",
		promptSnippet: "Read task context",
		parameters: Type.Object({
			task: Type.Number({ description: "Task index (0-based)" }),
		}),
		async execute(_id, params) {
			const target = requireTasks(runtime.state, params.task);
			return {
				content: [{ type: "text", text: buildTaskContext(target, params.task, runtime.state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
			const idx = args.task as number;
			const label = runtime.state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("get_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task loaded", theme);
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
			const target = requireTasks(runtime.state, params.task);

			if (target.status === "deleted") {
				throw new Error(`Task ${params.task} is already deleted.`);
			}

			// If deleting the active task, no need to reassign
			target.status = "deleted";
			runtime.updateWidget();
			runtime.persistState();
			return {
				content: [{ type: "text", text: buildStateSnapshot(runtime.state) }],
				details: undefined,
			};
		},
		renderCall(args, theme) {
			const { Text } = require("@earendil-works/pi-tui");
			const idx = args.task as number;
			const label = runtime.state.tasks[idx]?.label ?? "...";
			const preview = label.length > 50 ? `${label.slice(0, 50)}...` : label;
			return new Text(theme.fg("toolTitle", theme.bold("delete_task ")) + theme.fg("dim", `[${idx}] ${preview}`), 0, 0);
		},
		renderResult(_result, { isPartial }, theme) {
			if (isPartial) return renderPartial(theme);
			return renderSuccess("task deleted", theme);
		},
	});
}
