export type AgentMode = "worker" | "supervisor";

type AgentModeListener = (mode: AgentMode) => void;

const DEFAULT_AGENT_MODE: AgentMode = "supervisor";

let mode: AgentMode = DEFAULT_AGENT_MODE;
const listeners = new Set<AgentModeListener>();

function setAgentMode(nextMode: AgentMode): AgentMode {
	if (mode === nextMode) return mode;

	mode = nextMode;
	for (const listener of listeners) {
		listener(mode);
	}
	return mode;
}

export function isSupervisorMode(): boolean {
	return mode === "supervisor";
}

export function toggleAgentMode(): AgentMode {
	return setAgentMode(isSupervisorMode() ? "worker" : "supervisor");
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
