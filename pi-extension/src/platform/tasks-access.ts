import type { TasksAccess } from "../workflow/tasks/tasks.ts";

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
