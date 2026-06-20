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

interface AgentModeRuntime {
	mode: AgentMode;
	listeners: Set<AgentModeListener>;
}

const agentModeKey = Symbol.for("basecamp.agentMode");

type GlobalWithAgentMode = typeof globalThis & {
	[agentModeKey]?: AgentModeRuntime;
};

function getAgentModeRuntime(): AgentModeRuntime {
	const globalObject = globalThis as GlobalWithAgentMode;
	globalObject[agentModeKey] ??= { mode: DEFAULT_AGENT_MODE, listeners: new Set() };
	globalObject[agentModeKey].listeners ??= new Set();
	return globalObject[agentModeKey];
}

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
	const index = AGENT_MODES.indexOf(getAgentMode());
	return setAgentMode(AGENT_MODES[(index + 1) % AGENT_MODES.length]!);
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
