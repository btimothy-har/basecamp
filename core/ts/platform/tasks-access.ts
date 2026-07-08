/**
 * Tasks access contract + registry.
 *
 * Pi-core owns the TasksAccess interface and the registry cell.
 * Pi-tasks implements TasksAccess and registers it via registerTasksAccess().
 * Companion and swarm observe via getTasksAccess() (returns null if pi-tasks not installed).
 *
 * Process-scoped via globalThis so `/reload` preserves the registered access.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentMode } from "../session/agent-mode.ts";

// ---------------------------------------------------------------------------
// Shared type contracts (owned by pi-core, consumed by pi-tasks, pi-companion, pi-swarm)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Registry (process-scoped via globalThis)
// ---------------------------------------------------------------------------

interface TasksAccessState {
	access: TasksAccess | null;
}

const tasksAccessKey = Symbol.for("basecamp.tasksAccess");

type GlobalWithTasksAccess = typeof globalThis & {
	[tasksAccessKey]?: TasksAccessState;
};

function getTasksAccessState(): TasksAccessState {
	const globalObject = globalThis as GlobalWithTasksAccess;
	globalObject[tasksAccessKey] ??= { access: null };
	return globalObject[tasksAccessKey];
}

export function registerTasksAccess(access: TasksAccess): void {
	getTasksAccessState().access = access;
}

export function getTasksAccess(): TasksAccess | null {
	return getTasksAccessState().access;
}
