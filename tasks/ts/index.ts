import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerPlan, registerPlanCommands } from "./planning/plan.ts";
import { registerPlanCopilotGuard } from "./planning/plan-copilot-guard.ts";
import { registerPlanSkillGuard } from "./planning/plan-skill-guard.ts";
import { registerTasks } from "./tasks/tasks.ts";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	// Copilot guard first so its message wins over the plan-skill guard for a blocked plan() in copilot.
	registerPlanCopilotGuard(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
}

// Public surface for other contexts (imported via #tasks/index.ts only).
export { isPlanDisabledFor, PLAN_TOOL_NAME } from "./planning/plan-copilot-guard.ts";
export type { GoalCycle, ReviewState, Task, TaskStatus, TasksAccess, TasksState } from "./tasks/access.ts";
export { getTasksAccess, registerTasksAccess } from "./tasks/access.ts";
