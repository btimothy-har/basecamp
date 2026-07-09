import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { processScoped } from "#core/platform/global-registry.ts";
import { getInvokedSkills } from "#core/platform/skill-tracker.ts";
import { getWorkspaceService, getWorkspaceState } from "#core/platform/workspace.ts";
import { getAgentMode, onAgentModeChange } from "#core/session/agent-mode.ts";
import { getCurrentSessionState, onCurrentSessionTitleChange } from "#core/state/index.ts";
import { getTasksAccess } from "#tasks/index.ts";
import { reportHerdrMetadata } from "./herdr-metadata.ts";
import {
	buildSnapshot,
	type CompanionSnapshotWorktree,
	companionLiveSnapshotPath,
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
	unsubscribeAgentMode: (() => void) | null;
	unsubscribeTitle: (() => void) | null;
}

// Surviving state: the live companion wiring outlives /reload.
const getCompanionState = processScoped<CompanionState>("basecamp.companion", () => ({
	ctx: null,
	unsubscribeWorkspace: null,
	unsubscribeAgentMode: null,
	unsubscribeTitle: null,
}));

function clearSubscriptions(state: CompanionState): void {
	state.unsubscribeWorkspace?.();
	state.unsubscribeWorkspace = null;
	state.unsubscribeAgentMode?.();
	state.unsubscribeAgentMode = null;
	state.unsubscribeTitle?.();
	state.unsubscribeTitle = null;
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

function writeNow(pi: ExtensionAPI): void {
	const state = getCompanionState();
	const ctx = state.ctx;
	if (!ctx) return;

	try {
		const tasksState = getTasksAccess()?.getState();
		const sessionId = ctx.sessionManager.getSessionId();
		let title: string | null = null;
		try {
			title = getCurrentSessionState().title;
		} catch {
			title = null;
		}
		const snapshot = buildSnapshot({
			sessionId,
			title,
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
		writeSnapshotFile(companionLiveSnapshotPath(), snapshot);
		void reportHerdrMetadata(pi, snapshot);
	} catch {
		// best effort
	}
}

export default function registerCompanion(pi: ExtensionAPI): void {
	if (Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0) return;

	const state = getCompanionState();
	clearSubscriptions(state);

	pi.on("session_start", (_event, sessionCtx) => {
		clearSubscriptions(state);
		state.ctx = sessionCtx;
		writeNow(pi);
		state.unsubscribeWorkspace = getWorkspaceService()?.onChange?.(() => writeNow(pi)) ?? null;
		state.unsubscribeAgentMode = onAgentModeChange(() => writeNow(pi));
		state.unsubscribeTitle = onCurrentSessionTitleChange(() => writeNow(pi));
	});

	pi.on("tool_result", (event) => {
		if (event.isError || !TRIGGER_TOOLS.has(event.toolName)) return;
		writeNow(pi);
	});

	pi.on("session_shutdown", (event) => {
		if (event.reason === "quit" && state.ctx) {
			try {
				removeSnapshotFile(companionSnapshotPath(state.ctx.sessionManager.getSessionId()));
				removeSnapshotFile(companionLiveSnapshotPath());
			} catch {
				// best effort
			}
		}

		clearSubscriptions(state);
		state.ctx = null;
	});
}
