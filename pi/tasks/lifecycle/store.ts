/** File persistence — ~/.pi/basecamp/tasks/<session-id>.json */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "#core/host/paths.ts";
import type { GoalCycle } from "../schemas/task.ts";

export function defaultTasksDir(homeDir = os.homedir()): string {
	return path.join(basecampRoot(homeDir), "tasks");
}

export function tasksFilePath(sessionId: string, dir = defaultTasksDir()): string {
	return path.join(dir, `${sessionId}.json`);
}

export const TASKS_SCHEMA_VERSION = 1;

interface TasksFile {
	version: number;
	cycles: GoalCycle[];
}

/**
 * Drop any legacy `notes` key left on persisted tasks (the annotate_task field
 * was removed). Mutates in place — the parsed objects are throwaway.
 */
function stripLegacyNotes(cycles: GoalCycle[]): GoalCycle[] {
	for (const cycle of cycles) {
		if (!Array.isArray(cycle?.tasks)) continue;
		for (const task of cycle.tasks) {
			if (task && typeof task === "object") delete (task as { notes?: unknown }).notes;
		}
	}
	return cycles;
}

/** Read the versioned envelope, migrating a legacy bare-array file on read. */
export function loadCycles(filePath: string): GoalCycle[] {
	try {
		const parsed: unknown = JSON.parse(fs.readFileSync(filePath, "utf8"));
		if (Array.isArray(parsed)) return stripLegacyNotes(parsed as GoalCycle[]);
		if (parsed && typeof parsed === "object" && Array.isArray((parsed as TasksFile).cycles)) {
			return stripLegacyNotes((parsed as TasksFile).cycles);
		}
		return [];
	} catch {
		return [];
	}
}

export function saveCycles(filePath: string, cycles: GoalCycle[]): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	const payload: TasksFile = { version: TASKS_SCHEMA_VERSION, cycles };
	fs.writeFileSync(tmp, JSON.stringify(payload, null, 2));
	fs.renameSync(tmp, filePath);
}
