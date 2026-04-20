/**
 * Worktree — creation via --label flag and tool-level enforcement.
 *
 * Two-layer defense when a worktree is active:
 *   1. Prompt: env block tells model to use worktree dir with absolute paths
 *   2. Tool guards:
 *      - read/edit/write/grep/find/ls: block if path resolves under main repo
 *      - bash: prepend cd <worktree> so commands run in the right cwd
 *
 * Worktree metadata is stored in ~/.worktrees/<repo>/.meta/<label>.json
 * by the Python git/worktrees.py module. This module reads that metadata
 * and creates worktrees via git CLI.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import type { SessionState } from "../../config";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WORKTREES_DIR = path.join(os.homedir(), ".worktrees");

// ---------------------------------------------------------------------------
// Worktree creation
// ---------------------------------------------------------------------------

interface WorktreeResult {
	worktreeDir: string;
	branch: string;
	created: boolean;
}

/**
 * Get or create a worktree for a project.
 *
 * Checks ~/.worktrees/<repo>/<label>/ first. If it exists and has valid
 * metadata, returns it. Otherwise creates a new worktree via git.
 */
export async function getOrCreateWorktree(
	pi: ExtensionAPI,
	primaryDir: string,
	repoName: string,
	label: string,
	projectName: string,
): Promise<WorktreeResult> {
	const worktreeDir = path.join(WORKTREES_DIR, repoName, label);
	const branch = `wt/${label}`;
	const metaDir = path.join(WORKTREES_DIR, repoName, ".meta");
	const metaFile = path.join(metaDir, `${label}.json`);

	// Check if worktree already exists
	if (fs.existsSync(worktreeDir) && fs.existsSync(metaFile)) {
		// Read branch from metadata
		try {
			const meta = JSON.parse(fs.readFileSync(metaFile, "utf8"));
			return {
				worktreeDir,
				branch: meta.branch ?? branch,
				created: false,
			};
		} catch {
			// Metadata corrupt — fall through to create
		}
	}

	// Create parent directories
	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });

	// Create the worktree
	const result = await pi.exec("git", ["-C", primaryDir, "worktree", "add", "-b", branch, worktreeDir], {
		timeout: 30_000,
	});

	if (result.code !== 0) {
		throw new Error(`Failed to create worktree: ${result.stderr}`);
	}

	// Write metadata
	fs.mkdirSync(metaDir, { recursive: true });
	const meta = {
		name: label,
		path: worktreeDir,
		branch,
		created_at: new Date().toISOString(),
		project: projectName,
		repo_name: repoName,
		source_dir: primaryDir,
	};
	fs.writeFileSync(metaFile, JSON.stringify(meta, null, 2));

	return { worktreeDir, branch, created: true };
}

// ---------------------------------------------------------------------------
// Tool guards
// ---------------------------------------------------------------------------

/** Expand ~ in path (mirrors pi's path-utils expandPath). */
function expandPath(filePath: string): string {
	const normalized = filePath.startsWith("@") ? filePath.slice(1) : filePath;
	if (normalized === "~") return os.homedir();
	if (normalized.startsWith("~/")) return os.homedir() + normalized.slice(1);
	return normalized;
}

/** Shell-quote a string for safe embedding in bash commands. */
function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

/**
 * Register tool_call guards for worktree enforcement.
 *
 * Only active when state.worktreeDir is set.
 */
export function registerWorktreeGuards(pi: ExtensionAPI, getState: () => SessionState): void {
	pi.on("tool_call", async (event, ctx) => {
		const state = getState();
		if (!state.worktreeDir) return;

		const mainRepo = ctx.cwd;
		const worktreeDir = state.worktreeDir;

		// --- Bash: rewrite cwd ---
		if (isToolCallEventType("bash", event)) {
			const cmd = event.input.command;
			if (cmd && !cmd.startsWith(`cd ${worktreeDir}`)) {
				event.input.command = `cd ${shellQuote(worktreeDir)} && ${cmd}`;
			}
			return;
		}

		// --- Path-based tools: block if resolves under main repo ---
		const pathTools = ["read", "edit", "write", "grep", "find", "ls"];
		if (!pathTools.includes(event.toolName)) return;

		const inputPath = (event.input as { path?: string }).path;
		if (!inputPath) return;

		const expanded = expandPath(inputPath);
		const resolved = path.isAbsolute(expanded) ? path.resolve(expanded) : path.resolve(mainRepo, expanded);

		// Allow secondary project dirs
		if (state.secondaryDirs.some((d: string) => resolved === d || resolved.startsWith(`${d}/`))) {
			return;
		}

		// Allow anything outside main repo (scratch, /tmp, ~, etc.)
		if (resolved !== mainRepo && !resolved.startsWith(`${mainRepo}/`)) {
			return;
		}

		// It's under main repo — block unless it's also under worktree
		if (!resolved.startsWith(`${worktreeDir}/`) && resolved !== worktreeDir) {
			return {
				block: true,
				reason:
					`Path "${inputPath}" resolves to main repo (${mainRepo}). ` +
					`Use absolute path under worktree: ${worktreeDir}`,
			};
		}
	});
}
