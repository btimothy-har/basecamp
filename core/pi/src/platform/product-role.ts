/**
 * Session product-role override seam.
 *
 * Pi-core owns the provider contract and the registry cell. Feature packages can
 * register a narrow provider for session product-role overrides that must be
 * available before session_start handler ordering is known. Consumers (e.g.
 * pi-swarm's daemon identity derivation) read it before falling back to env or
 * agent-mode. Absent a provider, callers degrade to null.
 *
 * Process-scoped via globalThis so `/reload` preserves the registered provider.
 */

export interface SessionProductRoleProvider {
	/** The product role override for the current session, or null when not applicable. */
	resolveProductRole(): string | null;
}

interface SessionProductRoleState {
	provider: SessionProductRoleProvider | null;
}

const sessionProductRoleKey = Symbol.for("basecamp.sessionProductRole");

type GlobalWithSessionProductRole = typeof globalThis & {
	[sessionProductRoleKey]?: SessionProductRoleState;
};

function getSessionProductRoleState(): SessionProductRoleState {
	const globalObject = globalThis as GlobalWithSessionProductRole;
	globalObject[sessionProductRoleKey] ??= { provider: null };
	return globalObject[sessionProductRoleKey];
}

export function registerSessionProductRoleProvider(provider: SessionProductRoleProvider): void {
	getSessionProductRoleState().provider = provider;
}

export function getSessionProductRoleProvider(): SessionProductRoleProvider | null {
	return getSessionProductRoleState().provider;
}

export function resetSessionProductRoleForTesting(): void {
	getSessionProductRoleState().provider = null;
}

export function resolveSessionProductRoleOverride(): string | null {
	try {
		return getSessionProductRoleProvider()?.resolveProductRole() ?? null;
	} catch {
		return null;
	}
}
