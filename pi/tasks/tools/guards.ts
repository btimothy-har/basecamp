/**
 * Tool-call guards — the tasks domain's tool_call policy.
 *
 *   - Task gate: require a goal before proceeding, and open tasks before
 *     editing files; plus the complete_task stop-work notifier.
 *   - Copilot plan guard: hard-block plan() in copilot sessions.
 *   - Skill plan guard: require the planning skill before interactive plan().
 *
 * Registered by the composition root; copilot before skill so its message wins.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isCopilotMode, PLAN_TOOL_NAME } from "#core/agent-mode/copilot.ts";
import { getAgentMode } from "#core/agent-mode/index.ts";
import { isSubagent } from "#core/host/env.ts";
import { hasInvokedSkill } from "#core/skills/tracker.ts";
import type { TasksRuntime } from "../lifecycle/index.ts";
import { isCompleteTaskStopWorkDetails } from "../lifecycle/text.ts";

const TASK_TOOLS = new Set([
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"get_task",
	"delete_task",
	"escalate",
	"plan",
	"skill",
	"read",
]);
const GATED_WITHOUT_TASKS = new Set(["edit", "write"]);

/** Require a goal (and open tasks before edit/write); notify on stop-work completion. */
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

/**
 * Hard-blocks plan() in copilot sessions. Copilot stages work via
 * launch_workstream and never implements in-session. Registered before the
 * skill guard so the copilot-specific reason is what the agent sees.
 */
export function registerPlanCopilotGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event) => {
		if (event.toolName !== PLAN_TOOL_NAME) return;
		if (!isCopilotMode(getAgentMode())) return;
		return {
			block: true,
			reason: "plan() is disabled in copilot sessions — stage work with launch_workstream instead.",
		};
	});
}

const PLANNING_SKILL = "planning";

/** Requires the planning skill before interactive main-session plan() calls. */
export function registerPlanSkillGuard(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "plan") return;
		if (!ctx.hasUI) return;
		if (isSubagent()) return;
		if (hasInvokedSkill(PLANNING_SKILL)) return;

		return {
			block: true,
			reason: `The plan tool requires the ${PLANNING_SKILL} skill in interactive main sessions. Call skill({ name: "${PLANNING_SKILL}" }) first, then retry plan.`,
		};
	});
}
