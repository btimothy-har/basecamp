/**
 * Current-agent-identity seam.
 *
 * Pi-core owns the provider contract and the registry cell. pi-swarm registers a
 * provider that derives the running session's public daemon handle from its
 * ExtensionContext; consumers (e.g. pi-tasks' /workstream) read it to stamp the
 * session handle onto a launch record. Absent pi-swarm, callers degrade to null.
 *
 * Process-scoped via globalThis so `/reload` preserves the registered provider.
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export interface AgentIdentityProvider {
	/** The public daemon handle for the session bound to `ctx`, or null when unavailable. */
	deriveHandle(ctx: ExtensionContext): string | null;
}

interface AgentIdentityState {
	provider: AgentIdentityProvider | null;
}

const agentIdentityKey = Symbol.for("basecamp.agentIdentity");

type GlobalWithAgentIdentity = typeof globalThis & {
	[agentIdentityKey]?: AgentIdentityState;
};

function getAgentIdentityState(): AgentIdentityState {
	const globalObject = globalThis as GlobalWithAgentIdentity;
	globalObject[agentIdentityKey] ??= { provider: null };
	return globalObject[agentIdentityKey];
}

export function registerAgentIdentityProvider(provider: AgentIdentityProvider): void {
	getAgentIdentityState().provider = provider;
}

export function getAgentIdentityProvider(): AgentIdentityProvider | null {
	return getAgentIdentityState().provider;
}

export function resetAgentIdentityForTesting(): void {
	getAgentIdentityState().provider = null;
}

export function deriveCurrentAgentHandle(ctx: ExtensionContext): string | null {
	try {
		return getAgentIdentityProvider()?.deriveHandle(ctx) ?? null;
	} catch {
		return null;
	}
}
