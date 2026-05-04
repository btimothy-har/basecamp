import {
	getCurrentSessionState,
	SESSION_STATE_AGENT_MODES,
	type SessionStateAgentMode,
	updateCurrentSessionStateIfInitialized,
} from "../state/index.ts";

export type AgentMode = SessionStateAgentMode;

export const AGENT_MODES: readonly AgentMode[] = SESSION_STATE_AGENT_MODES;

const DEFAULT_AGENT_MODE: AgentMode = "executor";

type AgentModeListener = (mode: AgentMode) => void;

let mode: AgentMode = DEFAULT_AGENT_MODE;
const listeners = new Set<AgentModeListener>();

function updateLiveAgentMode(nextMode: AgentMode): AgentMode {
	if (mode === nextMode) return mode;

	mode = nextMode;
	for (const listener of listeners) {
		listener(mode);
	}
	return mode;
}

export function getAgentMode(): AgentMode {
	return mode;
}

export function setAgentMode(nextMode: AgentMode): AgentMode {
	updateCurrentSessionStateIfInitialized({ agentMode: nextMode });
	return updateLiveAgentMode(nextMode);
}

export function restoreAgentModeFromSessionState(): AgentMode {
	return updateLiveAgentMode(getCurrentSessionState().agentMode ?? DEFAULT_AGENT_MODE);
}

export function cycleAgentMode(): AgentMode {
	const index = AGENT_MODES.indexOf(getAgentMode());
	return setAgentMode(AGENT_MODES[(index + 1) % AGENT_MODES.length]!);
}

export function resetAgentMode(): void {
	setAgentMode(DEFAULT_AGENT_MODE);
}

export function onAgentModeChange(listener: AgentModeListener): () => void {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
}
