/**
 * Process-scoped model alias provider registry.
 *
 * The owning model-aliases extension provides configuration-backed aliases;
 * consumers depend only on this seam.
 */

export interface ModelAlias {
	alias: string;
	model: string;
	providerId: string;
}

export interface ModelAliasProvider {
	id: string;
	resolve(alias: string): string | undefined;
	list(): ModelAlias[];
}

// Wiring, not surviving state: providers re-register on every load.
const providers = new Map<string, ModelAliasProvider>();

export function registerModelAliasProvider(provider: ModelAliasProvider): void {
	providers.set(provider.id, provider);
}

export function resolveModelAlias(alias: string): string | undefined {
	for (const provider of Array.from(providers.values()).reverse()) {
		const model = provider.resolve(alias);
		if (model) return model;
	}
	return undefined;
}

export function listModelAliases(): ModelAlias[] {
	return Array.from(providers.values()).flatMap((provider) => provider.list());
}

export function clearModelAliasProvidersForTesting(): void {
	providers.clear();
}
