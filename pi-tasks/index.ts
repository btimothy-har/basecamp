import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerEscalate } from "pi-core/escalate/tool.ts";
import { isSubagent } from "pi-core/platform/env.ts";
import { registerAgents } from "./src/agents/index.ts";
import { registerPlan, registerPlanCommands } from "./src/planning/plan";
import { registerPlanSkillGuard } from "./src/planning/plan-skill-guard";
import { registerTasks } from "./src/tasks/tasks";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
	registerAgents(pi);

	// Escalate is also registered by pi-core for primary sessions.
	// This duplicate registration is harmless (idempotent) and will be
	// removed in the cutover phase when agents/ is cleaned up.
	if (!isSubagent()) {
		registerEscalate(pi);
	}
}
