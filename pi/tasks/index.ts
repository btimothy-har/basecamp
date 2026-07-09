import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerTasks } from "./lifecycle/index.ts";
import { registerPlanCopilotGuard } from "./planning/guards/plan-copilot.ts";
import { registerPlanSkillGuard } from "./planning/guards/plan-skill.ts";
import { registerPlan, registerPlanCommands } from "./planning/index.ts";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	// Copilot guard first so its message wins over the plan-skill guard for a blocked plan() in copilot.
	registerPlanCopilotGuard(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
}

export type { GoalCycle, ReviewState, Task, TaskStatus, TasksAccess, TasksState } from "./lifecycle/access.ts";
export { getTasksAccess, registerTasksAccess } from "./lifecycle/access.ts";
// Public surface for other contexts (imported via #tasks/index.ts only).
export { isPlanDisabledFor, PLAN_TOOL_NAME } from "./planning/guards/plan-copilot.ts";
