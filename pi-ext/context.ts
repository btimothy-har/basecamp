/**
 * Shared context builders — reusable prompt fragments.
 *
 * Pure functions that format state into text blocks for prompt injection.
 * Used by both the parent session prompt (core/src/prompt.ts) and
 * the worker prompt builder (agents/src/spawner.ts).
 *
 * Each function returns null when the context is not applicable,
 * so callers can filter with a simple truthiness check.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { SessionState } from "./config";

// ============================================================================
// Types
// ============================================================================

export interface GitStatus {
	branch: string | null;
	mainBranch: string;
	status: string;
	recentCommits: string;
}

/**
 * Build the worktree warning block.
 *
 * Returns null if no worktree is active. When active, this is
 * safety-critical — the model must use absolute paths targeting
 * the worktree directory, not the main branch checkout.
 */
export function buildWorktreeWarning(state: SessionState): string | null {
	if (!state.worktreeDir || !state.worktreeLabel) return null;

	return [
		`Worktree: ${state.worktreeLabel}`,
		"",
		"⚠ WORKTREE ACTIVE: Isolated git worktree. Use absolute paths for all file operations. Bash runs in the working directory automatically.",
	].join("\n");
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
export function buildProjectContext(state: SessionState, contextFiles?: ContextFile[]): string | null {
	const parts: string[] = [];

	// Basecamp project context
	if (state.contextContent) {
		parts.push(state.contextContent);
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

/**
 * Format a git status snapshot for inclusion in a prompt.
 *
 * The snapshot is taken at session start and does not update
 * during the conversation — the model is told this explicitly.
 */
export function buildGitContext(git: GitStatus): string {
	const lines = [
		"gitStatus: This is the git status at the start of the conversation. " +
			"Note that this status is a snapshot in time, and will not update during the conversation.",
		`Current branch: ${git.branch ?? "unknown"}`,
		"",
		`Main branch (you will usually use this for PRs): ${git.mainBranch}`,
		"",
		"Status:",
		git.status || "(clean)",
		"",
		"Recent commits:",
		git.recentCommits,
	];
	return lines.join("\n");
}

// ============================================================================
// Capabilities Index
// ============================================================================

/**
 * Build a compact capabilities index for the system prompt.
 *
 * Lists only names grouped by type, plus instructions for the discover
 * tool. Replaces the previous verbose XML/list builders that dumped
 * full descriptions into the prompt.
 *
 * The model uses the `discover` tool for details on any item.
 */
export function buildCapabilitiesIndex(opts: {
	toolNames: string[];
	skillNames: string[];
	agentNames: string[];
	includeAgents: boolean;
}): string {
	const lines: string[] = [];

	const summaryCounts = [
		`${opts.toolNames.length} tools`,
		`${opts.skillNames.length} skills`,
		...(opts.includeAgents ? [`${opts.agentNames.length} agents`] : []),
	];
	lines.push(`Available in this session: ${summaryCounts.join(", ")}.`);
	lines.push("");

	if (opts.toolNames.length > 0) {
		lines.push(`Tools (${opts.toolNames.length}): ${opts.toolNames.join(", ")}`);
	}
	if (opts.skillNames.length > 0) {
		lines.push(`Skills (${opts.skillNames.length}): ${opts.skillNames.join(", ")}`);
	}
	if (opts.includeAgents && opts.agentNames.length > 0) {
		lines.push(`Agents (${opts.agentNames.length}): ${opts.agentNames.join(", ")}`);
	}

	lines.push(
		"",
		"Use `discover` to browse, search, or get details on any listed item.",
		"Use `skill` to load a skill's full instructions into context before using it.",
		"",
		"`discover` modes:",
		'- List a category with descriptions: `discover({ type: "skills" })`',
		'- Search by keyword: `discover({ type: "skills", query: "python" })`',
		'- Get details for one item: `discover({ name: "python-development" })`',
		"",
		"`skill` example:",
		'- Load skill instructions: `skill({ name: "python-development" })`',
	);

	return lines.join("\n");
}
