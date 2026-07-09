/**
 * Task guardrails — the tool_call gate that requires a goal (and open tasks
 * before edit/write), plus the complete_task stop-work notifier.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isCompleteTaskStopWorkDetails } from "./context.ts";
import type { TasksRuntime } from "./tasks.ts";

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
	"skill",
	"read",
]);
const GATED_WITHOUT_TASKS = new Set(["edit", "write"]);

export function registerTaskGuards(pi: ExtensionAPI, runtime: TasksRuntime): void {
	pi.on("tool_call", async (event) => {
		if (TASK_TOOLS.has(event.toolName)) return;

		let reason: string | null = null;
		if (!runtime.state.goal) {
			reason = "Set a goal with update_goal before proceeding.";
		} else if (GATED_WITHOUT_TASKS.has(event.toolName)) {
			const hasOpenTasks = runtime.state.tasks.some((t) => t.status === "pending" || t.status === "active");
			if (!hasOpenTasks) {
				reason = "Break work into tasks with create_tasks before editing files.";
			}
		}

		if (!reason) return;

		// First violation: hard block. Subsequent: soft steer.
		if (runtime.guardBlockCount === 0) {
			runtime.guardBlockCount++;
			return { block: true, reason };
		}

		runtime.guardBlockCount++;
		pi.sendMessage({ customType: "tasks-guard", content: reason, display: false }, { deliverAs: "steer" });
	});

	pi.on("tool_result", async (event, eventCtx) => {
		if (event.toolName !== "complete_task" || event.isError) return;
		if (!isCompleteTaskStopWorkDetails(event.details)) return;

		if (eventCtx.hasUI) {
			eventCtx.ui.notify(event.details.stop_message ?? "Stopping work now.", "info");
		}
	});
}
