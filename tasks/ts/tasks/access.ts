/**
 * Tasks access contract + registration point.
 *
 * The tasks module implements TasksAccess and registers it at load time; the
 * companion module observes via getTasksAccess() (null until tasks registers).
 * The composition root re-runs registration on every load (including /reload),
 * so plain module state suffices — durability lives in the on-disk tasks store.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentMode } from "#core/session/agent-mode.ts";

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

export interface TasksAccess {
	getState(): Readonly<TasksState>;
	setNotes(index: number, notes: string): void;
	activateGoalCycle(goal: string, tasks: Task[], planRef: GoalCycle["planRef"], agentMode: AgentMode | null): void;
	getPlanRef(): GoalCycle["planRef"];
	getContext(): ExtensionContext | null;
}

let registeredAccess: TasksAccess | null = null;

export function registerTasksAccess(access: TasksAccess): void {
	registeredAccess = access;
}

export function getTasksAccess(): TasksAccess | null {
	return registeredAccess;
}
