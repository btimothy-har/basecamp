/** Pure task-state text builders: steer content, snapshots, task context. */

import type { GoalCycle, Task, TaskStatus, TasksState } from "#tasks/schemas/task.ts";

export function requireTasks(state: TasksState, index: number): Task {
	if (state.tasks.length === 0) throw new Error("No tasks exist. Use create_tasks first.");
	if (!Number.isInteger(index) || index < 0 || index >= state.tasks.length) {
		throw new Error(`Invalid task index ${index}. Valid range: 0–${state.tasks.length - 1}.`);
	}
	return state.tasks[index]!;
}

export function buildSteerContent(state: TasksState, planRef: GoalCycle["planRef"]): string | null {
	if (!state.goal) return null;

	const lines = [`Current progress:`, `Goal: ${state.goal}`];

	// Include plan context for drift prevention
	if (planRef) {
		lines.push("");
		lines.push(`Design: ${planRef.design}`);
		lines.push(`Boundaries: ${planRef.boundaries}`);
	}

	if (state.tasks.length > 0) {
		const live = state.tasks.filter((t) => t.status !== "deleted");
		const completedCount = live.filter((t) => t.status === "completed").length;
		lines.push("");
		lines.push(`Completed: ${completedCount}/${live.length}`);
		lines.push("");

		const markers: Record<TaskStatus, string> = { completed: "✓", active: "→", pending: "☐", deleted: "✕" };
		for (let i = 0; i < state.tasks.length; i++) {
			const t = state.tasks[i]!;
			if (t.status === "deleted") continue;
			lines.push(`  [${i}] ${markers[t.status]} ${t.label}`);
		}
	}

	lines.push(
		"",
		"Call start_task before beginning work on a task, and complete_task when it is done. When the work reaches a natural handoff, stop calling tools and close out with a summary of what you did. If blocked before the task is done, escalate instead. If the plan changes, call create_tasks with the updated list.",
	);
	return lines.join("\n");
}

export function buildProgress(state: TasksState): { completed: number; deleted: number; total: number } {
	const deleted = state.tasks.filter((t) => t.status === "deleted").length;
	const live = state.tasks.length - deleted;
	const completed = state.tasks.filter((t) => t.status === "completed").length;
	return { completed, deleted, total: live };
}

export function buildStateSnapshot(state: TasksState): string {
	const tasks: Record<string, { label: string; status: string }> = {};
	for (let i = 0; i < state.tasks.length; i++) {
		const t = state.tasks[i]!;
		if (t.status === "deleted") continue;
		tasks[i] = { label: t.label, status: t.status };
	}

	return JSON.stringify({
		goal: state.goal,
		progress: buildProgress(state),
		tasks,
	});
}

export function buildTaskContext(task: Task, index: number, state: TasksState): string {
	return JSON.stringify({
		index,
		label: task.label,
		status: task.status,
		description: task.description,
		criteria: task.criteria,
		progress: buildProgress(state),
	});
}

export interface CompleteTaskResultDetails {
	task: number;
	label: string;
	progress: ReturnType<typeof buildProgress>;
}

export function buildCompleteTaskResultText(state: TasksState, index: number, task: Task): string {
	const progress = buildProgress(state);
	return [
		`Task ${index} completed: ${task.label}.`,
		`Progress: ${progress.completed}/${progress.total} tasks completed.`,
		"",
		buildStateSnapshot(state),
	].join("\n");
}
