import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readModelAliasConfig } from "./aliases.ts";
import { registerModelAliasCommands } from "./commands.ts";

/**
 * Model alias provider registry — the seam consumers depend on, plus the
 * native config-backed provider basecamp registers into it. The seam owns no
 * config or policy of its own: providers register in, and resolveModelAlias
 * fans out across them (most-recently-registered first).
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

const PROVIDER_ID = "native-config";

export function createNativeConfigModelAliasProvider(configPath?: string): ModelAliasProvider {
	return {
		id: PROVIDER_ID,
		resolve(alias: string): string | undefined {
			return readModelAliasConfig(configPath)[alias];
		},
		list(): ModelAlias[] {
			return Object.entries(readModelAliasConfig(configPath)).map(([alias, model]) => ({
				alias,
				model,
				providerId: PROVIDER_ID,
			}));
		},
	};
}

export default function (pi: ExtensionAPI): void {
	registerModelAliasProvider(createNativeConfigModelAliasProvider());
	registerModelAliasCommands(pi);
}
