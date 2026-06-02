import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getInvokedSkills } from "../platform/skill-tracker.ts";
import { getTasksAccess } from "../platform/tasks-access.ts";
import { getWorkspaceService, getWorkspaceState } from "../platform/workspace.ts";
import { getAgentMode } from "../session/agent-mode.ts";
import {
	buildSnapshot,
	type CompanionSnapshotWorktree,
	companionSnapshotPath,
	removeSnapshotFile,
	writeSnapshotFile,
} from "./snapshot.ts";

const TRIGGER_TOOLS = new Set([
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"annotate_task",
	"delete_task",
	"plan",
	"skill",
]);

interface CompanionState {
	ctx: ExtensionContext | null;
	unsubscribeWorkspace: (() => void) | null;
}

const companionKey = Symbol.for("basecamp.companion");

type GlobalWithCompanion = typeof globalThis & {
	[companionKey]?: CompanionState;
};

function getCompanionState(): CompanionState {
	const globalObject = globalThis as GlobalWithCompanion;
	globalObject[companionKey] ??= { ctx: null, unsubscribeWorkspace: null };
	return globalObject[companionKey];
}

function clearWorkspaceSubscription(state: CompanionState): void {
	if (!state.unsubscribeWorkspace) return;
	state.unsubscribeWorkspace();
	state.unsubscribeWorkspace = null;
}

function getWorktreeSnapshot(): CompanionSnapshotWorktree | null {
	const worktree = getWorkspaceState()?.activeWorktree;
	if (!worktree) return null;
	return {
		label: worktree.label,
		branch: worktree.branch,
		path: worktree.path,
	};
}

function writeNow(): void {
	const state = getCompanionState();
	const ctx = state.ctx;
	if (!ctx) return;

	try {
		const tasksState = getTasksAccess()?.getState();
		const sessionId = ctx.sessionManager.getSessionId();
		const snapshot = buildSnapshot({
			sessionId,
			goal: tasksState?.goal ?? null,
			rawTasks:
				tasksState?.tasks.map((task) => ({
					label: task.label,
					status: task.status,
					notes: task.notes,
				})) ?? [],
			agentMode: getAgentMode(),
			worktree: getWorktreeSnapshot(),
			repoName: getWorkspaceState()?.repo?.name ?? null,
			model: ctx.model?.id ?? null,
			skillsUsed: [...getInvokedSkills()],
			effectiveCwd: getWorkspaceService()?.getEffectiveCwd?.() ?? process.cwd(),
		});
		writeSnapshotFile(companionSnapshotPath(sessionId), snapshot);
	} catch {
		// best effort
	}
}

export default function registerCompanion(pi: ExtensionAPI): void {
	const state = getCompanionState();
	clearWorkspaceSubscription(state);

	pi.on("session_start", (_event, sessionCtx) => {
		clearWorkspaceSubscription(state);
		state.ctx = sessionCtx;
		writeNow();
		state.unsubscribeWorkspace =
			getWorkspaceService()?.onChange?.(() => {
				writeNow();
			}) ?? null;
	});

	pi.on("tool_result", (event) => {
		if (event.isError || !TRIGGER_TOOLS.has(event.toolName)) return;
		writeNow();
	});

	pi.on("session_shutdown", (event) => {
		if (event.reason === "quit" && state.ctx) {
			try {
				removeSnapshotFile(companionSnapshotPath(state.ctx.sessionManager.getSessionId()));
			} catch {
				// best effort
			}
		}

		clearWorkspaceSubscription(state);
		state.ctx = null;
	});
}
