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

// Wiring, not surviving state: the provider re-registers on every load.
let sessionProductRoleProvider: SessionProductRoleProvider | null = null;

export function registerSessionProductRoleProvider(provider: SessionProductRoleProvider): void {
	if (sessionProductRoleProvider && sessionProductRoleProvider !== provider) {
		console.warn("basecamp: replacing an existing session product-role provider");
	}
	sessionProductRoleProvider = provider;
}

export function getSessionProductRoleProvider(): SessionProductRoleProvider | null {
	return sessionProductRoleProvider;
}

export function resetSessionProductRoleForTesting(): void {
	sessionProductRoleProvider = null;
}

export function resolveSessionProductRoleOverride(): string | null {
	try {
		return getSessionProductRoleProvider()?.resolveProductRole() ?? null;
	} catch {
		return null;
	}
}
