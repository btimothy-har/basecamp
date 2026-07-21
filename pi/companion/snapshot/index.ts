import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentMode, onAgentModeChange } from "#core/agent-mode/index.ts";
import { processScoped } from "#core/global-registry.ts";
import { isSubagent } from "#core/host/env.ts";
import { getWorkspaceEffectiveCwd, getWorkspaceState, onWorkspaceChange } from "#core/project/workspace/state.ts";
import { getCurrentSessionState, onCurrentSessionTitleChange } from "#core/session/state/index.ts";
import { getInvokedSkills } from "#core/skills/tracker.ts";
import { observeRunSummary } from "#core/swarm/agents/summary-observer.ts";
import type { RunSummaryResult } from "#core/swarm/agents/view/summary.ts";
import { getTasksReader } from "#tasks/index.ts";
import { buildHerdrMetadata, type HerdrStatusContext, reportHerdrMetadata } from "../herdr/metadata.ts";
import {
	buildSnapshot,
	type CompanionSnapshot,
	type CompanionSnapshotWorktree,
	companionLiveSnapshotPath,
	companionSnapshotPath,
	removeSnapshotFile,
	writeSnapshotFile,
} from "./model.ts";

const TRIGGER_TOOLS = new Set([
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"delete_task",
	"plan",
	"skill",
]);

interface CompanionState {
	ctx: ExtensionContext | null;
	snapshot: CompanionSnapshot | null;
	activeAgentCount: number | null;
	primaryIdle: boolean;
	waitingToolCallIds: Set<string>;
	lastHerdrMetadataKey: string | null;
	unsubscribeWorkspace: (() => void) | null;
	unsubscribeAgentMode: (() => void) | null;
	unsubscribeTitle: (() => void) | null;
	unsubscribeSummary: (() => void) | null;
}

// Surviving state: the live companion wiring outlives /reload.
const getStoredCompanionState = processScoped<CompanionState>("basecamp.companion", () => ({
	ctx: null,
	snapshot: null,
	activeAgentCount: null,
	primaryIdle: true,
	waitingToolCallIds: new Set(),
	lastHerdrMetadataKey: null,
	unsubscribeWorkspace: null,
	unsubscribeAgentMode: null,
	unsubscribeTitle: null,
	unsubscribeSummary: null,
}));

function getCompanionState(): CompanionState {
	const state = getStoredCompanionState();
	// A live /reload can reuse state created before these fields existed.
	state.snapshot ??= null;
	state.activeAgentCount ??= null;
	state.primaryIdle ??= true;
	state.waitingToolCallIds ??= new Set();
	state.lastHerdrMetadataKey ??= null;
	state.unsubscribeSummary ??= null;
	return state;
}

function clearSubscriptions(state: CompanionState): void {
	state.unsubscribeWorkspace?.();
	state.unsubscribeWorkspace = null;
	state.unsubscribeAgentMode?.();
	state.unsubscribeAgentMode = null;
	state.unsubscribeTitle?.();
	state.unsubscribeTitle = null;
	state.unsubscribeSummary?.();
	state.unsubscribeSummary = null;
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

function herdrStatusContext(state: CompanionState): HerdrStatusContext {
	return {
		primaryIdle: state.primaryIdle,
		waitingForAgents: state.waitingToolCallIds.size > 0,
		activeAgentCount: state.activeAgentCount,
	};
}

function reportMetadataNow(pi: ExtensionAPI): void {
	const state = getCompanionState();
	if (!state.snapshot) return;
	const status = herdrStatusContext(state);
	const metadataKey = JSON.stringify(buildHerdrMetadata(state.snapshot, status));
	if (metadataKey === state.lastHerdrMetadataKey) return;
	state.lastHerdrMetadataKey = metadataKey;
	void reportHerdrMetadata(pi, state.snapshot, status);
}

function updateRunSummary(pi: ExtensionAPI, summary: RunSummaryResult | null): void {
	const state = getCompanionState();
	const activeAgentCount = summary?.counts ? summary.counts.pending + summary.counts.running : null;
	if (activeAgentCount === state.activeAgentCount) return;
	state.activeAgentCount = activeAgentCount;
	reportMetadataNow(pi);
}

function setPrimaryIdle(pi: ExtensionAPI, primaryIdle: boolean): void {
	const state = getCompanionState();
	if (state.primaryIdle === primaryIdle) return;
	state.primaryIdle = primaryIdle;
	reportMetadataNow(pi);
}

function writeNow(pi: ExtensionAPI): void {
	const state = getCompanionState();
	const ctx = state.ctx;
	if (!ctx) return;

	try {
		const tasksState = getTasksReader()?.getState();
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
				})) ?? [],
			agentMode: getAgentMode(),
			worktree: getWorktreeSnapshot(),
			repoName: getWorkspaceState()?.repo?.name ?? null,
			model: ctx.model?.id ?? null,
			skillsUsed: [...getInvokedSkills()],
			effectiveCwd: getWorkspaceEffectiveCwd(),
		});
		state.snapshot = snapshot;
		writeSnapshotFile(companionSnapshotPath(sessionId), snapshot);
		writeSnapshotFile(companionLiveSnapshotPath(), snapshot);
		reportMetadataNow(pi);
	} catch {
		// best effort
	}
}

export default function registerCompanion(pi: ExtensionAPI): void {
	if (isSubagent()) return;

	const state = getCompanionState();
	clearSubscriptions(state);
	state.waitingToolCallIds.clear();

	pi.on("session_start", (_event, sessionCtx) => {
		clearSubscriptions(state);
		state.ctx = sessionCtx;
		state.snapshot = null;
		state.activeAgentCount = null;
		state.primaryIdle = sessionCtx.isIdle();
		state.waitingToolCallIds.clear();
		state.lastHerdrMetadataKey = null;
		state.unsubscribeSummary = observeRunSummary((summary) => updateRunSummary(pi, summary));
		writeNow(pi);
		state.unsubscribeWorkspace = onWorkspaceChange(() => writeNow(pi));
		state.unsubscribeAgentMode = onAgentModeChange(() => writeNow(pi));
		state.unsubscribeTitle = onCurrentSessionTitleChange(() => writeNow(pi));
	});

	pi.on("agent_start", () => setPrimaryIdle(pi, false));
	pi.on("agent_settled", () => setPrimaryIdle(pi, true));

	pi.on("tool_execution_start", (event) => {
		if (event.toolName !== "wait_for_agent") return;
		const wasWaiting = state.waitingToolCallIds.size > 0;
		state.waitingToolCallIds.add(event.toolCallId);
		if (!wasWaiting) reportMetadataNow(pi);
	});

	pi.on("tool_execution_end", (event) => {
		if (event.toolName !== "wait_for_agent" || !state.waitingToolCallIds.delete(event.toolCallId)) return;
		if (state.waitingToolCallIds.size === 0) reportMetadataNow(pi);
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
		state.snapshot = null;
		state.activeAgentCount = null;
		state.waitingToolCallIds.clear();
		state.lastHerdrMetadataKey = null;
	});
}
