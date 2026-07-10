/**
 * Session agent-role override seam.
 *
 * Core owns the provider contract and the registry cell. Other contexts can
 * register a narrow provider for session agent-role overrides that must be
 * available before session_start handler ordering is known. Consumers (e.g.
 * the swarm context's daemon identity derivation) read it before falling back to
 * env or agent-mode. Absent a provider, callers degrade to null.
 *
 * Process-scoped via globalThis so `/reload` preserves the registered provider.
 */

export interface AgentRoleProvider {
	/** The agent role override for the current session, or null when not applicable. */
	resolveAgentRole(): string | null;
}

// Wiring, not surviving state: the provider re-registers on every load.
let agentRoleProvider: AgentRoleProvider | null = null;

export function registerAgentRoleProvider(provider: AgentRoleProvider): void {
	if (agentRoleProvider && agentRoleProvider !== provider) {
		console.warn("basecamp: replacing an existing session agent-role provider");
	}
	agentRoleProvider = provider;
}

export function getAgentRoleProvider(): AgentRoleProvider | null {
	return agentRoleProvider;
}

export function resetAgentRoleForTesting(): void {
	agentRoleProvider = null;
}

export function resolveAgentRoleOverride(): string | null {
	try {
		return getAgentRoleProvider()?.resolveAgentRole() ?? null;
	} catch {
		return null;
	}
}
