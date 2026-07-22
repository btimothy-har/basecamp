/**
 * Task-domain data models — the shared vocabulary of goals and tasks.
 *
 * These are the types shared by the task lifecycle, workflows, and tools. They
 * import nothing from tasks itself — the bottom of the domain's dependency
 * graph.
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
