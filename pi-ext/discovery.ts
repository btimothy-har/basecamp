/**
 * Agent discovery — three-tier scan with frontmatter parsing.
 *
 * Shared module: used by both agents/src (tool registration) and
 * core/src (prompt assembly for agent listing in system prompt).
 *
 * Priority (highest wins on name collision):
 *   1. User:    ~/.pi/agents/
 *   2. Builtin: pi-ext/agents/builtin/ (shipped with basecamp)
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

// ============================================================================
// Types
// ============================================================================

/**
 * Model resolution strategy for an agent.
 *
 * - "inherit"  — use the spawning parent's current model
 * - "default"  — use pi's default model (no --model flag)
 * - string     — model alias (e.g. "fast") or explicit model ID; aliases
 *                are resolved from ~/.pi/basecamp/config.json `models` map
 */
export type ModelStrategy = "inherit" | "default" | (string & {});

export interface AgentConfig {
	name: string;
	description: string;
	model: ModelStrategy;
	thinking?: string;
	tools?: string[];
	skills?: string[];
	systemPrompt: string;
	source: "builtin" | "user";
	filePath: string;
}

// ============================================================================
// Constants
// ============================================================================

const USER_AGENTS_DIR = path.join(os.homedir(), ".pi", "agents");
const BUILTIN_AGENTS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "agents", "builtin");

// ============================================================================
// Frontmatter Parser
// ============================================================================

interface ParsedFile {
	frontmatter: Record<string, string>;
	body: string;
}

function parseFrontmatter(content: string): ParsedFile {
	const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
	if (!match) return { frontmatter: {}, body: content.trim() };

	const fm: Record<string, string> = {};
	for (const line of match[1]!.split("\n")) {
		const colon = line.indexOf(":");
		if (colon === -1) continue;
		const key = line.slice(0, colon).trim();
		const value = line.slice(colon + 1).trim();
		if (key) fm[key] = value;
	}
	return { frontmatter: fm, body: match[2]!.trim() };
}

function parseCsv(value: string | undefined): string[] | undefined {
	if (!value) return undefined;
	const items = value
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean);
	return items.length > 0 ? items : undefined;
}

// ============================================================================
// Directory Scanner
// ============================================================================

function loadAgentsFromDir(dir: string, source: AgentConfig["source"]): AgentConfig[] {
	if (!fs.existsSync(dir)) return [];

	let entries: fs.Dirent[];
	try {
		entries = fs.readdirSync(dir, { withFileTypes: true });
	} catch {
		return [];
	}

	const agents: AgentConfig[] = [];
	for (const entry of entries) {
		if (!entry.name.endsWith(".md")) continue;
		if (!entry.isFile() && !entry.isSymbolicLink()) continue;

		const filePath = path.join(dir, entry.name);
		let content: string;
		try {
			content = fs.readFileSync(filePath, "utf-8");
		} catch {
			continue;
		}

		const { frontmatter: fm, body } = parseFrontmatter(content);
		if (!fm.name || !fm.description) continue;

		// Model strategy: "inherit", "default", or an explicit model string.
		// Missing model defaults to "default" (pi's default model).
		const model: ModelStrategy = (fm.model as ModelStrategy) || "default";

		agents.push({
			name: fm.name,
			description: fm.description,
			model,
			thinking: fm.thinking || undefined,
			tools: parseCsv(fm.tools),
			skills: parseCsv(fm.skills),
			systemPrompt: body,
			source,
			filePath,
		});
	}

	return agents;
}

// ============================================================================
// Public API
// ============================================================================

/**
 * Discover all agent definitions, merging by priority.
 * Project agents override user agents which override builtins.
 */
export function discoverAgents(_cwd: string): AgentConfig[] {
	const builtin = loadAgentsFromDir(BUILTIN_AGENTS_DIR, "builtin");
	const user = loadAgentsFromDir(USER_AGENTS_DIR, "user");

	// Name-keyed merge: last write wins (user > builtin)
	const map = new Map<string, AgentConfig>();
	for (const a of builtin) map.set(a.name, a);
	for (const a of user) map.set(a.name, a);
	return Array.from(map.values());
}
