/**
 * Shared capability catalog.
 *
 * Extensions register lightweight providers for capability metadata (tools,
 * skills, agents). Core consumes the catalog for prompt capability summaries,
 * while feature modules keep ownership of their own domain-specific discovery.
 *
 * Re-registering a provider with the same id replaces the previous provider;
 * the composition root re-registers everything on each load (including
 * /reload), so the registry is plain module state.
 */

export type CatalogType = "tools" | "skills" | "agents" | (string & {});

export interface CatalogItem {
	type: CatalogType;
	name: string;
	description: string;
	path?: string;
	meta?: Record<string, string>;
}

export interface CatalogContext {
	cwd: string;
}

export interface CatalogProvider {
	id: string;
	list(ctx: CatalogContext): CatalogItem[];
}

// Wiring, not surviving state: providers re-register on every load.
const providers = new Map<string, CatalogProvider>();

/** Register or replace a catalog provider. */
export function registerCatalogProvider(provider: CatalogProvider): void {
	providers.set(provider.id, provider);
}

/** Return all catalog items from currently registered providers. */
export function listCatalogItems(ctx: CatalogContext): CatalogItem[] {
	const items: CatalogItem[] = [];
	for (const provider of providers.values()) {
		items.push(...provider.list(ctx));
	}
	return items;
}

/** Return catalog items for one type from currently registered providers. */
export function listCatalogItemsByType(type: CatalogType, ctx: CatalogContext): CatalogItem[] {
	return listCatalogItems(ctx).filter((item) => item.type === type);
}
