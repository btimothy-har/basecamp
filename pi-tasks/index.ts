import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerPlan, registerPlanCommands } from "./src/planning/plan";
import { registerPlanSkillGuard } from "./src/planning/plan-skill-guard";
import { registerTasks } from "./src/tasks/tasks";
import { registerWorkstreamCommand } from "./src/workstreams/command.ts";
import { registerWorkstreamTools } from "./src/workstreams/tools.ts";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	registerPlanSkillGuard(pi);
	const plan = registerPlan(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
	registerWorkstreamTools(pi);
	registerWorkstreamCommand(pi);

	// The sync agent tool (agents/tool.ts) has been removed in the cutover.
	// pi-swarm/extension now provides the sole agent tool (daemon-backed).
	// The agents/ directory files (catalog, commands, discovery, etc.) are
	// owned by pi-swarm/extension which has its own copies.
}
