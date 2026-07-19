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

export function loadCycles(filePath: string): GoalCycle[] {
	try {
		const raw = fs.readFileSync(filePath, "utf8");
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed : [];
	} catch {
		return [];
	}
}

export function saveCycles(filePath: string, cycles: GoalCycle[]): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(cycles, null, 2));
	fs.renameSync(tmp, filePath);
}
