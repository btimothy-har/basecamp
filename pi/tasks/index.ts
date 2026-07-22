import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerTasks } from "./lifecycle/index.ts";
import { registerPlanCommands } from "./tools/commands.ts";
import { registerPlanCopilotGuard, registerPlanSkillGuard, registerTaskGuards } from "./tools/guards.ts";
import { registerPlan } from "./tools/plan-tool.ts";
import { registerTaskTools } from "./tools/task-tools.ts";

export default function (pi: ExtensionAPI) {
	const runtime = registerTasks(pi);
	registerTaskTools(pi, runtime);
	registerTaskGuards(pi, runtime);
	// Copilot guard before the skill guard so its message wins for a blocked plan() in copilot.
	registerPlanCopilotGuard(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, runtime);
	registerPlanCommands(pi, runtime, plan);
}

export type { GoalCycle, ReviewState, Task, TaskStatus, TasksState } from "./schemas/task.ts";
