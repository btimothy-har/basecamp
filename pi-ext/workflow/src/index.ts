/**
 * Workflow extension — task/planning lifecycle, agent dispatch, and collaboration.
 *
 * This is the single pi extension entry for workflow-related behavior.
 * Internal domains stay separated under src/tasks, src/planning,
 * src/agents, and src/escalate; this file only composes their registrations in order.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerAgents } from "./agents/index";
import { registerEscalate } from "./escalate/index.js";
import { registerPlan, registerPlanCommands } from "./planning/plan";
import { registerPlanSkillGuard } from "./planning/plan-skill-guard";
import { registerTasksCommand } from "./tasks/command";
import { registerTasks } from "./tasks/tasks";

export default function (pi: ExtensionAPI) {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	const tasks = registerTasks(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerTasksCommand(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
	registerAgents(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerEscalate(pi);
	}
}
