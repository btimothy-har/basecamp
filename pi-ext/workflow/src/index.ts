/**
 * Workflow extension — task/planning lifecycle plus agent dispatch.
 *
 * This is the single pi extension entry for workflow-related behavior.
 * Internal domains stay separated under src/tasks, src/planning, and
 * src/agents; this file only composes their registrations in order.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerAgents } from "./agents/index";
import { registerPlan, registerPlanCommands } from "./planning/plan";
import { registerPlanSkillGuard } from "./planning/plan-skill-guard";
import { registerTasksCommand } from "./tasks/command";
import { registerTasks } from "./tasks/tasks";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerTasksCommand(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
	registerAgents(pi);
}
