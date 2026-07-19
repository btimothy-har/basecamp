/**
 * Task-domain data models — the shared vocabulary of goals and tasks.
 *
 * These are the types other tasks layers (lifecycle/workflows/tools) and the
 * companion domain read. They import nothing from tasks itself — the bottom of
 * the domain's dependency graph.
 */

import type { AgentMode } from "#core/agent-mode/index.ts";

export type TaskStatus = "pending" | "active" | "completed" | "deleted";

export interface ReviewState {
	approved: boolean | null;
	feedback: string | null;
}

export interface Task {
	label: string;
	description: string;
	criteria: string;
	notes: string | null;
	status: TaskStatus;
	review: ReviewState | null;
}

export interface TasksState {
	goal: string | null;
	tasks: Task[];
}

export interface GoalCycle {
	goal: string;
	tasks: Task[];
	planRef: {
		context: string;
		design: string;
		success: string;
		boundaries: string;
	} | null;
	agentMode?: AgentMode | null;
	active: boolean;
	archivedAt: string | null;
}

/**
 * Read-only view of live task state, published by lifecycle for cross-domain
 * observers (companion). Reads only — mutation stays inside the tasks domain.
 */
export interface TasksReader {
	getState(): Readonly<TasksState>;
}
