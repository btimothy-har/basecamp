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
import { discoverAgents } from "../../../discovery";

const DEFAULT_AGENT_MAX_DEPTH = 2;

// ============================================================================
// Types
// ============================================================================

interface DiscoverableItem {
	name: string;
	kind: "tool" | "skill" | "agent";
	description: string;
	/** File path — skills and agents only. */
	path?: string;
	/** Extra metadata for detail view. */
	meta?: Record<string, string>;
}

// ============================================================================
// Data Collection
// ============================================================================

function collectTools(pi: ExtensionAPI): DiscoverableItem[] {
	const activeNames = new Set(pi.getActiveTools());
	return pi
		.getAllTools()
		.filter((t) => activeNames.has(t.name))
		.map((t) => ({
			name: t.name,
			kind: "tool" as const,
			description: t.description,
		}));
}

function collectSkills(pi: ExtensionAPI): DiscoverableItem[] {
	return pi
		.getCommands()
		.filter((c) => c.source === "skill")
		.map((c) => ({
			name: c.name.replace(/^skill:/, ""),
			kind: "skill" as const,
			description: c.description ?? "",
			path: c.sourceInfo.path,
		}));
}

function collectAgents(cwd: string): DiscoverableItem[] {
	// At max depth, agent tool isn't registered — don't show agents
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	if (depth >= maxDepth) return [];

	return discoverAgents(cwd).map((a) => ({
		name: a.name,
		kind: "agent" as const,
		description: a.description,
		path: a.filePath,
		meta: {
			source: a.source,
			model: a.model,
			...(a.tools ? { tools: a.tools.join(", ") } : {}),
			...(a.skills ? { skills: a.skills.join(", ") } : {}),
		},
	}));
}

// ============================================================================
// Search
// ============================================================================

/** Case-insensitive OR match: any keyword substring-matches name or description. */
function matchesQuery(item: DiscoverableItem, query: string): boolean {
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

function formatList(items: DiscoverableItem[]): string {
	if (items.length === 0) return "No results found.";

	return items
		.map((item) => {
			let line = `**${item.name}** (${item.kind})`;
			if (item.description) line += ` — ${item.description}`;
			return line;
		})
		.join("\n");
}

function formatDetail(item: DiscoverableItem): string {
	const lines: string[] = [`**${item.name}** (${item.kind})`];

	if (item.description) lines.push(`Description: ${item.description}`);
	if (item.path) lines.push(`Path: ${item.path}`);

	if (item.meta) {
		for (const [key, value] of Object.entries(item.meta)) {
			lines.push(`${key}: ${value}`);
		}
	}

	if (item.kind === "skill") {
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

			// Mode 1: Detail lookup by name
			if (name) {
				const all = [...collectTools(pi), ...collectSkills(pi), ...collectAgents(ctx.cwd)];
				const item = all.find((i) => i.name === name);

				if (!item) {
					const suggestions = all
						.filter((i) => i.name.includes(name.toLowerCase()))
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

			let items: DiscoverableItem[];
			switch (type) {
				case "tools":
					items = collectTools(pi);
					break;
				case "skills":
					items = collectSkills(pi);
					break;
				case "agents":
					items = collectAgents(ctx.cwd);
					break;
			}

			if (query) {
				items = items.filter((i) => matchesQuery(i, query));
			}

			return { details: null, content: [{ type: "text", text: formatList(items) }] };
		},
	});
}
