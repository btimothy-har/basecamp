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

	// The sync agent tool (agents/tool.ts) has been removed in the cutover.
	// pi-swarm/extension now provides the sole agent tool (daemon-backed).
	// The agents/ directory files (catalog, commands, discovery, etc.) are
	// owned by pi-swarm/extension which has its own copies.
	//
	// The workstream domain (launch_workstream, list_workstreams,
	// set_workstream_status, pi --workstream startup) has moved to
	// pi-swarm/extension/src/workstreams/ with daemon-backed persistence.
}
