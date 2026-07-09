/**
 * Process-scoped state that must survive `/reload`.
 *
 * Pi re-imports the extension with fresh module instances on /reload, so state
 * that must outlive a reload (live session state, sockets, invoked skills)
 * lives on globalThis behind a well-known Symbol key. Wiring — providers and
 * registries re-established by the composition root on every load —
 * deliberately does NOT use this helper; plain module state is correct there.
 * See core/README.md for the pattern.
 */
export function processScoped<T extends object>(key: `basecamp.${string}` | `pi.${string}`, init: () => T): () => T {
	const symbol = Symbol.for(key);
	const slots = globalThis as unknown as Record<symbol, T | undefined>;
	return () => (slots[symbol] ??= init());
}
