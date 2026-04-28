export type AgentMode = "planning" | "supervisor" | "executor";

export const AGENT_MODES: readonly AgentMode[] = ["planning", "supervisor", "executor"];

const DEFAULT_AGENT_MODE: AgentMode = "executor";

type AgentModeListener = (mode: AgentMode) => void;

let mode: AgentMode = DEFAULT_AGENT_MODE;
const listeners = new Set<AgentModeListener>();

export function getAgentMode(): AgentMode {
	return mode;
}

export function setAgentMode(nextMode: AgentMode): AgentMode {
	if (mode === nextMode) return mode;

	mode = nextMode;
	for (const listener of listeners) {
		listener(mode);
	}
	return mode;
}

export function cycleAgentMode(): AgentMode {
	const index = AGENT_MODES.indexOf(mode);
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
