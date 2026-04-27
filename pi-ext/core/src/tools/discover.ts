/**
 * Discover tool — browse, search, and inspect tools, skills, and agents.
 *
 * Replaces the previous pattern of dumping full catalogues into the
 * system prompt. The system prompt now contains only names; this tool
 * provides descriptions, paths, and metadata on demand.
 *
 * Three modes:
 *   - List all of a type:    { type: "skills" }
 *   - Keyword search:        { type: "skills", query: "python data" }
 *   - Single item detail:    { name: "python-development" }
 *
 * To load full skill instructions, use the `skill` tool instead.
 */
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import {
	type CatalogItem,
	type CatalogType,
	listCatalogItems,
	listCatalogItemsByType,
} from "../../../platform/catalog";

// ============================================================================
// Search
// ============================================================================

/** Case-insensitive OR match: any keyword substring-matches name or description. */
function matchesQuery(item: CatalogItem, query: string): boolean {
	const keywords = query
		.toLowerCase()
		.split(/\s+/)
		.filter((k) => k.length > 0);
	if (keywords.length === 0) return true;

	const haystack = `${item.name} ${item.description}`.toLowerCase();
	return keywords.some((kw) => haystack.includes(kw));
}

// ============================================================================
// Formatting
// ============================================================================

function formatKind(type: CatalogType): string {
	switch (type) {
		case "tools":
			return "tool";
		case "skills":
			return "skill";
		case "agents":
			return "agent";
		default:
			return type;
	}
}

function formatList(items: CatalogItem[]): string {
	if (items.length === 0) return "No results found.";

	return items
		.map((item) => {
			let line = `**${item.name}** (${formatKind(item.type)})`;
			if (item.description) line += ` — ${item.description}`;
			return line;
		})
		.join("\n");
}

function formatDetail(item: CatalogItem): string {
	const lines: string[] = [`**${item.name}** (${formatKind(item.type)})`];

	if (item.description) lines.push(`Description: ${item.description}`);
	if (item.path) lines.push(`Path: ${item.path}`);

	if (item.meta) {
		for (const [key, value] of Object.entries(item.meta)) {
			lines.push(`${key}: ${value}`);
		}
	}

	if (item.type === "skills") {
		lines.push("", `To load instructions, call: skill({ name: "${item.name}" })`);
	}

	return lines.join("\n");
}

// ============================================================================
// Tool Registration
// ============================================================================

const DiscoverParams = Type.Object(
	{
		type: Type.Optional(
			Type.Union([Type.Literal("skills"), Type.Literal("tools"), Type.Literal("agents")], {
				description: "Category to search. Required when listing or searching by keyword.",
			}),
		),
		query: Type.Optional(
			Type.String({
				description: "Keyword(s) to filter results. Space-separated, matched as OR against name and description.",
			}),
		),
		name: Type.Optional(
			Type.String({
				description: "Exact name of a specific tool, skill, or agent to get full details for.",
			}),
		),
	},
	{
		description:
			"Look up tools, skills, or agents. Use { type } to list a category, { type, query } to search, or { name } to get details on a specific item.",
	},
);

export function registerDiscoverTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "discover",
		label: "Discover",
		description:
			"Look up available tools, skills, and agents. " +
			'Use { type: "skills" } to list all skills, { type: "skills", query: "python" } to search, ' +
			'or { name: "python-development" } to get details on a specific item. ' +
			"To load full skill instructions, use the `skill` tool.",

		parameters: DiscoverParams,

		async execute(_id, params, _signal, _onUpdate, ctx) {
			const { type, query, name } = params;
			const catalogContext = { cwd: ctx.cwd };

			// Mode 1: Detail lookup by name
			if (name) {
				const all = listCatalogItems(catalogContext);
				const item = all.find((i) => i.name === name);

				if (!item) {
					const lowerName = name.toLowerCase();
					const suggestions = all
						.filter((i) => i.name.toLowerCase().includes(lowerName))
						.map((i) => i.name)
						.slice(0, 5);
					const hint = suggestions.length > 0 ? ` Did you mean: ${suggestions.join(", ")}?` : "";
					return {
						details: null,
						content: [{ type: "text", text: `No item found with name "${name}".${hint}` }],
					};
				}

				return { details: null, content: [{ type: "text", text: formatDetail(item) }] };
			}

			// Mode 2 & 3: List or search by type
			if (!type) {
				return {
					details: null,
					isError: true,
					content: [
						{
							type: "text",
							text: 'Provide either { name } for detail lookup or { type } to list/search a category (e.g. { type: "skills" }).',
						},
					],
				};
			}

			let items = listCatalogItemsByType(type, catalogContext);

			if (query) {
				items = items.filter((i) => matchesQuery(i, query));
			}

			return { details: null, content: [{ type: "text", text: formatList(items) }] };
		},
	});
}
