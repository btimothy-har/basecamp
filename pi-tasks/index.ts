import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerPlan, registerPlanCommands } from "./src/planning/plan";
import { registerPlanCopilotGuard } from "./src/planning/plan-copilot-guard";
import { registerPlanSkillGuard } from "./src/planning/plan-skill-guard";
import { registerTasks } from "./src/tasks/tasks";
import { registerWorkstreamStartup } from "./src/workstreams/start.ts";
import { registerWorkstreamTools } from "./src/workstreams/tools.ts";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	// Copilot guard first so its message wins over the plan-skill guard for a blocked plan() in copilot.
	registerPlanCopilotGuard(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
	registerWorkstreamTools(pi);
	registerWorkstreamStartup(pi);

	// The sync agent tool (agents/tool.ts) has been removed in the cutover.
	// pi-swarm/extension now provides the sole agent tool (daemon-backed).
	// The agents/ directory files (catalog, commands, discovery, etc.) are
	// owned by pi-swarm/extension which has its own copies.
}
