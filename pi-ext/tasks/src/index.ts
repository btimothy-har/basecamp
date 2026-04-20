/**
 * Tasks extension — goal/task tracking, planning, tools, widget, commands.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerTasksCommand } from "./command";
import { registerPlan, registerPlanCommands } from "./plan";
import { registerTasks } from "./tasks";

export default function (pi: ExtensionAPI) {
	const tasks = registerTasks(pi);
	const plan = registerPlan(pi, tasks);
	registerTasksCommand(pi, tasks);
	registerPlanCommands(pi, tasks, plan);
}
