/**
 * Current-agent-identity seam.
 *
 * Pi-core owns the provider contract and the registry cell. pi-swarm registers a
 * provider that derives the running session's public daemon handle from its
 * ExtensionContext; consumers (e.g. pi-swarm workstream startup) read it to attach
 * the running session as a workstream agent. Absent pi-swarm, callers degrade to null.
 *
 * Process-scoped via globalThis so `/reload` preserves the registered provider.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export interface AgentIdentityProvider {
	/** The public daemon handle for the session bound to `ctx`, or null when unavailable. */
	deriveHandle(ctx: ExtensionContext): string | null;
}

// Wiring, not surviving state: the provider re-registers on every load.
let agentIdentityProvider: AgentIdentityProvider | null = null;

export function registerAgentIdentityProvider(provider: AgentIdentityProvider): void {
	agentIdentityProvider = provider;
}

export function getAgentIdentityProvider(): AgentIdentityProvider | null {
	return agentIdentityProvider;
}

export function resetAgentIdentityForTesting(): void {
	agentIdentityProvider = null;
}

export function deriveCurrentAgentHandle(ctx: ExtensionContext): string | null {
	try {
		return getAgentIdentityProvider()?.deriveHandle(ctx) ?? null;
	} catch {
		return null;
	}
}
