/**
 * Shared prompt-fragment builders — reusable prompt text blocks.
 *
 * Pure functions that format workspace/project state into text blocks for
 * prompt injection. Each returns null when the context is not applicable, so
 * callers can filter with a simple truthiness check. The context-file loader
 * they pair with lives in #core/project/context.ts.
 */

import type { CatalogItem } from "#core/catalog/index.ts";
import type { ContextFile } from "#core/project/context.ts";
import type { WorkspaceState } from "#core/workspace/service.ts";

/**
 * Build the worktree warning block.
 *
 * Returns null if no worktree is active. When active, this is
 * safety-critical: by default project edits must happen in the worktree while
 * the protected checkout stays on the default branch with a clean status.
 */
export function buildWorktreeWarning(workspace: WorkspaceState | null): string | null {
	if (!workspace?.activeWorktree) return null;

	if (!workspace.unsafeEdit) {
		return "⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory. Do not edit the protected repository checkout.";
	}

	return [
		"⚠ WORKSPACE ACTIVE: Relative file-tool paths and bash commands run from the working directory.",
		buildUnsafeEditGuidance(workspace),
	].join("\n");
}

export function buildUnsafeEditGuidance(workspace: WorkspaceState | null): string | null {
	if (!workspace?.unsafeEdit) return null;

	const gitRestriction = workspace.activeWorktree
		? "Commits and mutating git commands must run from the active execution worktree."
		: "Commits and mutating git commands still require an active execution worktree.";

	return [
		"⚠ UNSAFE-EDIT MODE ACTIVE:",
		"- Parent file `edit`/`write` calls may modify the protected checkout directly.",
		`- ${gitRestriction}`,
		"- Subagents do not inherit unsafe-edit authority.",
	].join("\n");
}

/**
 * Format project context for the system prompt.
 *
 * Merges two sources:
 *   1. Project context (from the project resolver)
 *   2. Pi-native context files (AGENTS.md / CLAUDE.md walked from cwd)
 *
 * Returns null if neither source has content.
 */
export function buildProjectContext(
	project: { contextContent: string | null } | null,
	contextFiles?: ContextFile[],
): string | null {
	const parts: string[] = [];

	if (project?.contextContent) {
		parts.push(project.contextContent);
	}

	if (contextFiles && contextFiles.length > 0) {
		parts.push(
			"Project-specific instructions and guidelines:\n\n" +
				contextFiles.map((f) => `## ${f.path}\n\n${f.content}`).join("\n\n"),
		);
	}

	if (parts.length === 0) return null;
	return `# Project Context\n\n${parts.join("\n\n")}`;
}

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
