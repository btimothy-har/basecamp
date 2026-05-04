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

interface ModelAliasRuntime {
	providers: Map<string, ModelAliasProvider>;
}

const modelAliasesKey = Symbol.for("basecamp.model-aliases");

type GlobalWithModelAliases = typeof globalThis & {
	[modelAliasesKey]?: ModelAliasRuntime;
};

function getModelAliasRuntime(): ModelAliasRuntime {
	const globalObject = globalThis as GlobalWithModelAliases;
	globalObject[modelAliasesKey] ??= { providers: new Map() };
	return globalObject[modelAliasesKey];
}

export function registerModelAliasProvider(provider: ModelAliasProvider): void {
	getModelAliasRuntime().providers.set(provider.id, provider);
}

export function resolveModelAlias(alias: string): string | undefined {
	const providers = Array.from(getModelAliasRuntime().providers.values()).reverse();
	for (const provider of providers) {
		const model = provider.resolve(alias);
		if (model) return model;
	}
	return undefined;
}

export function listModelAliases(): ModelAlias[] {
	return Array.from(getModelAliasRuntime().providers.values()).flatMap((provider) => provider.list());
}

export function clearModelAliasProvidersForTesting(): void {
	getModelAliasRuntime().providers.clear();
}
