import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { AgentMode } from "../session/agent-mode.ts";
import type { GoalCycle, TaskStatus } from "../workflow/tasks/tasks.ts";

export const COMPANION_SNAPSHOT_VERSION = 1;
export const DEFAULT_COMPANION_DIR = path.join(os.homedir(), ".pi", "companion");

export interface CompanionSnapshotTask {
	label: string;
	description: string;
	criteria: string;
	status: TaskStatus;
	notes: string | null;
}

export interface CompanionSnapshotWorktree {
	label: string;
	branch: string | null;
	path: string;
}

export interface CompanionSnapshotGoal {
	goal: string;
	tasks: CompanionSnapshotTask[];
	agentMode: AgentMode | null;
	active: boolean;
	archivedAt: string | null;
	progress: { completed: number; total: number };
}

export interface CompanionSnapshot {
	version: typeof COMPANION_SNAPSHOT_VERSION;
	sessionId: string;
	title: string | null;
	updatedAt: string;
	goal: string | null;
	tasks: CompanionSnapshotTask[];
	progress: { completed: number; total: number };
	goals: CompanionSnapshotGoal[];
	agentMode: AgentMode | null;
	worktree: CompanionSnapshotWorktree | null;
	repoName: string | null;
	model: string | null;
	skillsUsed: string[];
	effectiveCwd: string;
}

export interface SnapshotInput {
	sessionId: string;
	title: string | null;
	goal: string | null;
	rawTasks: CompanionSnapshotTask[];
	cycles: readonly GoalCycle[];
	agentMode: AgentMode | null;
	worktree: CompanionSnapshotWorktree | null;
	repoName: string | null;
	model: string | null;
	skillsUsed: string[];
	effectiveCwd: string;
	now?: Date;
}

function snapshotFileName(sessionId: string): string {
	return `${sessionId.replace(/[^A-Za-z0-9_-]/g, "_")}.json`;
}

export function companionSnapshotPath(sessionId: string, dir = DEFAULT_COMPANION_DIR): string {
	return path.join(dir, snapshotFileName(sessionId));
}

export function buildSnapshot(input: SnapshotInput): CompanionSnapshot {
	const liveTasks = input.rawTasks.filter((task) => task.status !== "deleted");
	const completed = liveTasks.filter((task) => task.status === "completed").length;
	const goals: CompanionSnapshotGoal[] = input.cycles.map((cycle) => {
		const cycleLive = cycle.tasks.filter((task) => task.status !== "deleted");
		return {
			goal: cycle.goal,
			tasks: cycleLive.map((task) => ({
				label: task.label,
				description: task.description,
				criteria: task.criteria,
				status: task.status,
				notes: task.notes,
			})),
			agentMode: cycle.agentMode ?? null,
			active: cycle.active,
			archivedAt: cycle.archivedAt,
			progress: {
				completed: cycleLive.filter((task) => task.status === "completed").length,
				total: cycleLive.length,
			},
		};
	});

	return {
		version: COMPANION_SNAPSHOT_VERSION,
		sessionId: input.sessionId,
		title: input.title,
		updatedAt: (input.now ?? new Date()).toISOString(),
		goal: input.goal,
		tasks: liveTasks,
		progress: { completed, total: liveTasks.length },
		goals,
		agentMode: input.agentMode,
		worktree: input.worktree,
		repoName: input.repoName,
		model: input.model,
		skillsUsed: [...input.skillsUsed],
		effectiveCwd: input.effectiveCwd,
	};
}

export function writeSnapshotFile(filePath: string, snapshot: CompanionSnapshot): void {
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	const tmp = `${filePath}.tmp`;
	fs.writeFileSync(tmp, JSON.stringify(snapshot, null, 2));
	fs.renameSync(tmp, filePath);
}

export function removeSnapshotFile(filePath: string): void {
	try {
		fs.unlinkSync(filePath);
	} catch {
		// best effort
	}
}
