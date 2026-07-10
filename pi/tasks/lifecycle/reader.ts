/**
 * Cross-domain read handle for live task state.
 *
 * lifecycle registers a TasksReader at load; companion observes via
 * getTasksReader() (null until tasks registers). Plain module state — the
 * composition root re-registers on every load, so durability lives in the
 * on-disk tasks store, not here.
 */

import type { TasksReader } from "../schemas/task.ts";

let registeredReader: TasksReader | null = null;

export function registerTasksReader(reader: TasksReader): void {
	registeredReader = reader;
}

export function getTasksReader(): TasksReader | null {
	return registeredReader;
}
