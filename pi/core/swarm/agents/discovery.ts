/**
 * Agent discovery — basecamp-owned builtin definitions.
 *
 * Owned by the swarm context because agent definitions are part of the async-agent domain.
 * The host extension sees generic catalog metadata through the injected catalog provider.
 */

import * as fs from "node:fs";
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
 * - string     — explicit model ID passed directly to pi
 */
export type ModelStrategy = "inherit" | "default" | (string & {});

export interface AgentConfig {
	name: string;
	description: string;
	model: ModelStrategy;
	thinking?: string;
	systemPrompt: string;
	source: "builtin";
	filePath: string;
	// Fail-closed: read-only unless the frontmatter explicitly sets `readOnly: false`.
	// A mutative agent gets its own worktree + write/edit; read-only shares the parent's
	// worktree with a no-write toolset.
	readOnly: boolean;
}

// ============================================================================
// Constants
// ============================================================================

const BUILTIN_AGENTS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "builtin");

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

// ============================================================================
// Directory Scanner
// ============================================================================

function loadAgentsFromDir(dir: string): AgentConfig[] {
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
			systemPrompt: body,
			source: "builtin",
			filePath,
			readOnly: fm.readOnly !== "false",
		});
	}

	return agents;
}

// ============================================================================
// Public API
// ============================================================================

/** Discover all basecamp-owned agent definitions. */
export function discoverAgents(): AgentConfig[] {
	return loadAgentsFromDir(BUILTIN_AGENTS_DIR);
}
