import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerTasks } from "./lifecycle/index.ts";
import { registerPlanCopilotGuard } from "./planning/guards/plan-copilot.ts";
import { registerPlanSkillGuard } from "./planning/guards/plan-skill.ts";
import { registerPlan, registerPlanCommands } from "./planning/index.ts";

export default function (pi: ExtensionAPI) {
	const runtime = registerTasks(pi);
	// Copilot guard first so its message wins over the plan-skill guard for a blocked plan() in copilot.
	registerPlanCopilotGuard(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, runtime);
	registerPlanCommands(pi, runtime, plan);
}

// Public surface for other contexts (imported via #tasks/index.ts only).
export { getTasksReader, registerTasksReader } from "./lifecycle/reader.ts";
export type { GoalCycle, ReviewState, Task, TaskStatus, TasksState } from "./schemas/task.ts";
