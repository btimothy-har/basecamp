/**
 * Shared capability catalog.
 *
 * Extensions register lightweight providers for capability metadata (tools,
 * skills, agents). Core consumes the catalog for prompt capability summaries,
 * while feature modules keep ownership of their own domain-specific discovery.
 *
 * The registry is process-scoped via globalThis so it survives `/reload` in
 * the same pi process. Re-registering a provider with the same id replaces the
 * previous provider, which keeps reload behavior simple and duplicate-free.
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

interface CatalogState {
	providers: Map<string, CatalogProvider>;
}

const catalogKey = Symbol.for("basecamp.catalog");

type GlobalWithCatalog = typeof globalThis & {
	[catalogKey]?: CatalogState;
};

function getCatalogState(): CatalogState {
	const globalObject = globalThis as GlobalWithCatalog;
	globalObject[catalogKey] ??= { providers: new Map() };
	return globalObject[catalogKey];
}

/** Register or replace a catalog provider. */
export function registerCatalogProvider(provider: CatalogProvider): void {
	getCatalogState().providers.set(provider.id, provider);
}

/** Return all catalog items from currently registered providers. */
export function listCatalogItems(ctx: CatalogContext): CatalogItem[] {
	const items: CatalogItem[] = [];
	for (const provider of getCatalogState().providers.values()) {
		items.push(...provider.list(ctx));
	}
	return items;
}

/** Return catalog items for one type from currently registered providers. */
export function listCatalogItemsByType(type: CatalogType, ctx: CatalogContext): CatalogItem[] {
	return listCatalogItems(ctx).filter((item) => item.type === type);
}
