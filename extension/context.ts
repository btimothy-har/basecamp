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
import { escapeXml } from "./utils";

// ============================================================================
// Types
// ============================================================================

export interface GitStatus {
	branch: string | null;
	mainBranch: string;
	status: string;
	recentCommits: string;
}

/** Minimal tool info from pi.getAllTools() */
export interface ToolInfo {
	name: string;
	description: string;
}

/** Minimal skill info from pi.getCommands() filtered to source === "skill" */
export interface SkillInfo {
	name: string;
	description?: string;
	sourceInfo: { path: string };
}

/**
 * Build the worktree warning block.
 *
 * Returns null if no worktree is active. When active, this is
 * safety-critical — the model must use absolute paths targeting
 * the worktree directory, not the main branch checkout.
 */
export function buildWorktreeWarning(state: SessionState): string | null {
	if (!state.worktreeDir) return null;

	const lines = [
		`Worktree directory: ${state.worktreeDir}`,
	];
	if (state.worktreeBranch) {
		lines.push(`Worktree branch: ${state.worktreeBranch}`);
	}
	lines.push(
		"",
		"⚠ WORKTREE ACTIVE: All file operations (read, edit, write, bash) MUST target the "
		+ "worktree directory using absolute paths. The working directory contains the main "
		+ "branch checkout and must not be modified. Bash commands execute in the worktree "
		+ "directory automatically.",
	);
	return lines.join("\n");
}

/**
 * Format project context for the system prompt.
 *
 * Merges two sources:
 *   1. Basecamp project context (from ~/.basecamp/prompts/context/)
 *   2. Pi-native context files (AGENTS.md / CLAUDE.md walked from cwd)
 *
 * Returns null if neither source has content.
 */
export function buildProjectContext(
	state: SessionState,
	contextFiles?: ContextFile[],
): string | null {
	const parts: string[] = [];

	// Basecamp project context
	if (state.contextContent) {
		parts.push(state.contextContent);
	}

	// Pi-native context files (CLAUDE.md / AGENTS.md)
	if (contextFiles && contextFiles.length > 0) {
		parts.push(
			"Project-specific instructions and guidelines:\n\n"
			+ contextFiles.map((f) => `## ${f.path}\n\n${f.content}`).join("\n\n"),
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

function loadContextFileFromDir(dir: string): ContextFile | null {
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
		"gitStatus: This is the git status at the start of the conversation. "
		+ "Note that this status is a snapshot in time, and will not update during the conversation.",
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
// Tools & Skills
// ============================================================================

/**
 * Format the active tools list for the system prompt.
 *
 * Takes the output of pi.getAllTools() (filtered to active tools).
 * Each tool gets a one-line entry with a truncated description.
 * The model also receives full tool schemas separately — this
 * section is for orientation, not exhaustive documentation.
 *
 * Returns null if no tools are provided.
 */
export function buildToolsContext(tools: ToolInfo[]): string | null {
	if (tools.length === 0) return null;

	const lines = tools.map((t) => {
		const brief = firstSentence(t.description);
		return `- ${t.name}: ${brief}`;
	});
	return `Available tools:\n${lines.join("\n")}`;
}

/**
 * Format available skills for the system prompt.
 *
 * Matches the Agent Skills XML standard that models are trained on.
 * Takes skill commands from pi.getCommands() filtered to source === "skill".
 * The `name` field arrives as "skill:foo" from pi — we strip the prefix.
 *
 * Returns null if no skills are provided.
 */
export function buildSkillsContext(skills: SkillInfo[]): string | null {
	if (skills.length === 0) return null;

	const lines = [
		"The following skills provide specialized instructions for specific tasks.",
		"Use the read tool to load a skill's file when the task matches its description.",
		"When a skill file references a relative path, resolve it against the skill directory "
		+ "(parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.",
		"",
		"<available_skills>",
	];

	for (const skill of skills) {
		const name = skill.name.replace(/^skill:/, "");
		lines.push("  <skill>");
		lines.push(`    <name>${escapeXml(name)}</name>`);
		if (skill.description) {
			lines.push(`    <description>${escapeXml(skill.description)}</description>`);
		}
		lines.push(`    <location>${escapeXml(skill.sourceInfo.path)}</location>`);
		lines.push("  </skill>");
	}

	lines.push("</available_skills>");
	return lines.join("\n");
}

// ============================================================================
// Helpers
// ============================================================================

/** Extract the first sentence from a string (up to first period followed by space/end). */
function firstSentence(text: string): string {
	const match = text.match(/^[^.]*\./);
	return match ? match[0].trim() : text.trim();
}


