import { processScoped } from "../platform/global-registry.ts";
import {
	getCurrentSessionState,
	SESSION_STATE_AGENT_MODES,
	type SessionStateAgentMode,
	updateCurrentSessionStateIfInitialized,
} from "../session/state/index.ts";

export type AgentMode = SessionStateAgentMode;

export const AGENT_MODES: readonly AgentMode[] = SESSION_STATE_AGENT_MODES;
export const CYCLEABLE_AGENT_MODES: readonly AgentMode[] = AGENT_MODES.filter((mode) => mode !== "copilot");

const DEFAULT_AGENT_MODE: AgentMode = "executor";

type AgentModeListener = (mode: AgentMode) => void;

interface AgentModeRuntime {
	mode: AgentMode;
	listeners: Set<AgentModeListener>;
}

const getAgentModeRuntime = processScoped<AgentModeRuntime>("basecamp.agentMode", () => ({
	mode: DEFAULT_AGENT_MODE,
	listeners: new Set(),
}));

function updateLiveAgentMode(nextMode: AgentMode): AgentMode {
	const runtime = getAgentModeRuntime();
	if (runtime.mode === nextMode) return runtime.mode;

	runtime.mode = nextMode;
	for (const listener of runtime.listeners) {
		listener(runtime.mode);
	}
	return runtime.mode;
}

export function getAgentMode(): AgentMode {
	return getAgentModeRuntime().mode;
}

export function setAgentMode(nextMode: AgentMode): AgentMode {
	updateCurrentSessionStateIfInitialized({ agentMode: nextMode });
	return updateLiveAgentMode(nextMode);
}

export function restoreAgentModeFromSessionState(): AgentMode {
	return updateLiveAgentMode(getCurrentSessionState().agentMode ?? DEFAULT_AGENT_MODE);
}

export function cycleAgentMode(): AgentMode {
	const currentMode = getAgentMode();
	if (isCopilotMode(currentMode)) return currentMode;

	const index = CYCLEABLE_AGENT_MODES.indexOf(currentMode);
	return setAgentMode(CYCLEABLE_AGENT_MODES[(index + 1) % CYCLEABLE_AGENT_MODES.length]!);
}

export function resetAgentMode(): void {
	setAgentMode(DEFAULT_AGENT_MODE);
}

export function onAgentModeChange(listener: AgentModeListener): () => void {
	const runtime = getAgentModeRuntime();
	runtime.listeners.add(listener);
	return () => {
		runtime.listeners.delete(listener);
	};
}

/**
 * The Pi built-in plan() tool name. basecamp does not define plan() — it gates
 * it: copilot sessions hard-block the tool (the tasks guard) and filter it out
 * of the capabilities index (workspace's prompt assembly). Both consult
 * isCopilotMode together with this constant.
 */
export const PLAN_TOOL_NAME = "plan";

/**
 * copilot is the locked, launch-only mode (entered via `pi --copilot`). Used to
 * gate copilot-only behavior — notably that plan() is unavailable in copilot.
 */
export function isCopilotMode(mode: AgentMode): boolean {
	return mode === "copilot";
}
