/**
 * Shared context builders — reusable prompt fragments.
 *
 * Pure functions that format state into text blocks for prompt injection.
 * Used by the parent session prompt (core/src/prompt/prompt.ts) and other
 * runtime components that need consistent prompt context.
 *
 * Each function returns null when the context is not applicable,
 * so callers can filter with a simple truthiness check.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { CatalogItem } from "./catalog";
import type { BasecampProjectState } from "./config";
import type { WorkspaceState } from "./workspace";

/**
 * Build the worktree warning block.
 *
 * Returns null if no worktree is active. When active, this is
 * safety-critical: project edits must happen in the worktree while the
 * protected checkout stays on the default branch with a clean status.
 */
export function buildWorktreeWarning(workspace: WorkspaceState | null): string | null {
	if (!workspace?.executionTarget) return null;

	return "⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory. Do not edit the protected repository checkout.";
}

/**
 * Format project context for the system prompt.
 *
 * Merges two sources:
 *   1. Basecamp project context (from ~/.pi/context/)
 *   2. Pi-native context files (AGENTS.md / CLAUDE.md walked from cwd)
 *
 * Returns null if neither source has content.
 */
export function buildProjectContext(project: BasecampProjectState | null, contextFiles?: ContextFile[]): string | null {
	const parts: string[] = [];

	// Basecamp project context
	if (project?.contextContent) {
		parts.push(project.contextContent);
	}

	// Pi-native context files (CLAUDE.md / AGENTS.md)
	if (contextFiles && contextFiles.length > 0) {
		parts.push(
			"Project-specific instructions and guidelines:\n\n" +
				contextFiles.map((f) => `## ${f.path}\n\n${f.content}`).join("\n\n"),
		);
	}

	if (parts.length === 0) return null;
	return `# Project Context\n\n${parts.join("\n\n")}`;
}

// ============================================================================
// Context File Discovery
// ============================================================================

export interface ContextFile {
	path: string;
	content: string;
}

const CONTEXT_FILE_NAMES = ["AGENTS.md", "CLAUDE.md"];

export function loadContextFileFromDir(dir: string): ContextFile | null {
	for (const filename of CONTEXT_FILE_NAMES) {
		const filePath = path.join(dir, filename);
		try {
			const content = fs.readFileSync(filePath, "utf-8");
			return { path: filePath, content };
		} catch {
			// Not found, try next candidate
		}
	}
	return null;
}

/**
 * Discover AGENTS.md / CLAUDE.md files by walking up from cwd.
 *
 * Matches pi's native discovery: checks each directory from cwd
 * to filesystem root, returns files in root-first order.
 * Deduplicates by path.
 */
export function discoverContextFiles(cwd: string): ContextFile[] {
	const files: ContextFile[] = [];
	const seen = new Set<string>();

	let dir = cwd;
	while (true) {
		const file = loadContextFileFromDir(dir);
		if (file && !seen.has(file.path)) {
			files.unshift(file); // root-first order
			seen.add(file.path);
		}
		const parent = path.dirname(dir);
		if (parent === dir) break;
		dir = parent;
	}

	return files;
}

// ============================================================================
// Capabilities Index
// ============================================================================

function normalizeCapabilityDescription(description: string): string {
	return description.trim().replace(/\s+/g, " ");
}

function formatCapabilityItem(item: CatalogItem): string {
	const description = normalizeCapabilityDescription(item.description);
	return description ? `- ${item.name} — ${description}` : `- ${item.name} — (no description)`;
}

function pushCapabilitySection(lines: string[], label: string, items: CatalogItem[]): void {
	if (items.length === 0) return;
	if (lines.at(-1) !== "") lines.push("");

	lines.push(`${label} (${items.length}):`);
	for (const item of items) {
		lines.push(formatCapabilityItem(item));
	}
}

function ensureBlankLine(lines: string[]): void {
	if (lines.at(-1) !== "") lines.push("");
}

/**
 * Build a compact capabilities index for the system prompt.
 *
 * Lists capability names and descriptions grouped by type. Full skill
 * instructions remain on demand through the `skill` tool.
 */
export function buildCapabilitiesIndex(opts: {
	toolItems: CatalogItem[];
	skillItems: CatalogItem[];
	agentItems: CatalogItem[];
	includeAgents: boolean;
}): string {
	const lines: string[] = [];
	const agentItems = opts.includeAgents ? opts.agentItems : [];

	const summaryCounts = [
		`${opts.toolItems.length} tools`,
		`${opts.skillItems.length} skills`,
		...(opts.includeAgents ? [`${agentItems.length} agents`] : []),
	];
	lines.push(`Available in this session: ${summaryCounts.join(", ")}.`);
	lines.push("");

	pushCapabilitySection(lines, "Tools", opts.toolItems);
	pushCapabilitySection(lines, "Skills", opts.skillItems);
	pushCapabilitySection(lines, "Agents", agentItems);

	ensureBlankLine(lines);
	lines.push(
		"Use `skill` to load a skill's full instructions into context before using it.",
		"",
		"`skill` example:",
		'- Load skill instructions: `skill({ name: "python-development" })`',
	);

	return lines.join("\n");
}
