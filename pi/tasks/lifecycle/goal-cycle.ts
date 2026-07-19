/**
 * Goal-cycle operations over the live TasksRuntime — starting a new cycle
 * (archiving the previous one) and reading the active plan reference.
 *
 * The task tools and the plan workflow drive these directly; there is no
 * runtime service-locator for same-domain work.
 */

import type { AgentMode } from "#core/agent-mode/index.ts";
import type { GoalCycle, Task } from "../schemas/task.ts";
import type { TasksRuntime } from "./index.ts";

/** Archive the currently-active cycle, if any, snapshotting its live tasks. */
function archiveActiveCycle(runtime: TasksRuntime): void {
	const active = runtime.cycles.find((c) => c.active);
	if (!active) return;
	active.tasks = runtime.state.tasks;
	active.active = false;
	active.archivedAt = new Date().toISOString();
}

/** Archive the active cycle and start a new one, making it the live state. */
export function startGoalCycle(
	runtime: TasksRuntime,
	cycle: { goal: string; tasks: Task[]; planRef: GoalCycle["planRef"]; agentMode: AgentMode | null },
): void {
	archiveActiveCycle(runtime);
	runtime.cycles.push({ ...cycle, active: true, archivedAt: null });
	runtime.state.goal = cycle.goal;
	runtime.state.tasks = cycle.tasks;
	runtime.guardBlockCount = 0;
	runtime.updateWidget();
	runtime.persistState();
}

/** The active cycle's plan reference, or null when there is no active plan. */
export function getActivePlanRef(runtime: TasksRuntime): GoalCycle["planRef"] {
	return runtime.cycles.find((c) => c.active)?.planRef ?? null;
}
