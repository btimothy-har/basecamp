export type AgentMode = "analysis" | "planning" | "supervisor" | "executor";

export const AGENT_MODES: readonly AgentMode[] = ["analysis", "planning", "supervisor", "executor"];

const DEFAULT_AGENT_MODE: AgentMode = "executor";

type AgentModeListener = (mode: AgentMode) => void;

type AgentModeState = {
	mode: AgentMode;
	listeners: Set<AgentModeListener>;
};

const MODE_STATE_KEY = "__basecampAgentModeState";

type GlobalWithAgentModeState = typeof globalThis & {
	[MODE_STATE_KEY]?: AgentModeState;
};

function getModeState(): AgentModeState {
	const scope = globalThis as GlobalWithAgentModeState;
	// Pi loads package extension entries with separate Jiti module caches, so
	// module-level state is not shared between extension entries.
	scope[MODE_STATE_KEY] ??= { mode: DEFAULT_AGENT_MODE, listeners: new Set() };
	return scope[MODE_STATE_KEY];
}

export function getAgentMode(): AgentMode {
	return getModeState().mode;
}

export function setAgentMode(nextMode: AgentMode): AgentMode {
	const state = getModeState();
	if (state.mode === nextMode) return state.mode;

	state.mode = nextMode;
	for (const listener of state.listeners) {
		listener(state.mode);
	}
	return state.mode;
}

export function cycleAgentMode(): AgentMode {
	const mode = getAgentMode();
	const index = AGENT_MODES.indexOf(mode);
	return setAgentMode(AGENT_MODES[(index + 1) % AGENT_MODES.length]!);
}

export function resetAgentMode(): void {
	setAgentMode(DEFAULT_AGENT_MODE);
}

export function onAgentModeChange(listener: AgentModeListener): () => void {
	const state = getModeState();
	state.listeners.add(listener);
	return () => {
		state.listeners.delete(listener);
	};
}
