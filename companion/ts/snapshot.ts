import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { basecampRoot } from "#core/platform/paths.ts";
import type { AgentMode } from "#core/session/agent-mode.ts";
import type { TaskStatus } from "#tasks/index.ts";

export const COMPANION_SNAPSHOT_VERSION = 1;

export function defaultCompanionSnapshotDir(homeDir = os.homedir()): string {
	return path.join(basecampRoot(homeDir), "companion", "snapshots");
}

export interface CompanionSnapshotTask {
	label: string;
	status: TaskStatus;
	notes: string | null;
}

export interface CompanionSnapshotWorktree {
	label: string;
	branch: string | null;
	path: string;
}

export interface CompanionSnapshot {
	version: typeof COMPANION_SNAPSHOT_VERSION;
	sessionId: string;
	title: string | null;
	updatedAt: string;
	goal: string | null;
	tasks: CompanionSnapshotTask[];
	progress: { completed: number; total: number };
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

function liveSnapshotFileName(processIdentifier: string): string {
	return `.live-${processIdentifier.replace(/[^A-Za-z0-9_-]/g, "_")}.json`;
}

export function companionSnapshotPath(sessionId: string, dir = defaultCompanionSnapshotDir()): string {
	return path.join(dir, snapshotFileName(sessionId));
}

export function companionLiveSnapshotPath(
	dir = defaultCompanionSnapshotDir(),
	processIdentifier = String(process.pid),
): string {
	return path.join(dir, liveSnapshotFileName(processIdentifier));
}

export function buildSnapshot(input: SnapshotInput): CompanionSnapshot {
	const liveTasks = input.rawTasks.filter((task) => task.status !== "deleted");
	const completed = liveTasks.filter((task) => task.status === "completed").length;
	return {
		version: COMPANION_SNAPSHOT_VERSION,
		sessionId: input.sessionId,
		title: input.title,
		updatedAt: (input.now ?? new Date()).toISOString(),
		goal: input.goal,
		tasks: liveTasks,
		progress: { completed, total: liveTasks.length },
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
