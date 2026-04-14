/**
 * Prompt Assembly — builds the basecamp system prompt layers.
 *
 * Registers before_agent_start hook to prepend basecamp's prompt
 * before pi's default system prompt each turn.
 *
 * Reads bundled prompt files (environment.md, system.md, working styles)
 * and assembles them with runtime context (env block, git status).
 *
 * User overrides in ~/.basecamp/prompts/ take precedence over bundled defaults.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { type SessionState, getTimezone, getLogseqGraph } from "../../config";
import { getState, getGitStatus } from "./session";

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

/** Bundled prompt files shipped with the extension package. */
const PACKAGE_DIR = path.resolve(__dirname, "system-prompts");

/** User overrides — checked first before falling back to package defaults. */
const USER_PROMPTS_DIR = path.join(os.homedir(), ".basecamp", "prompts");
const USER_STYLES_DIR = path.join(USER_PROMPTS_DIR, "working_styles");

// ---------------------------------------------------------------------------
// File loading (user override → package default)
// ---------------------------------------------------------------------------

function loadPromptFile(filename: string): string {
	// Check user override
	const userPath = path.join(USER_PROMPTS_DIR, filename);
	try {
		return fs.readFileSync(userPath, "utf8");
	} catch {
		// Fall through to package default
	}

	const packagePath = path.join(PACKAGE_DIR, filename);
	try {
		return fs.readFileSync(packagePath, "utf8");
	} catch {
		return "";
	}
}

function loadWorkingStyle(name: string): string {
	// Check user override
	const userPath = path.join(USER_STYLES_DIR, `${name}.md`);
	try {
		return fs.readFileSync(userPath, "utf8");
	} catch {
		// Fall through to package default
	}

	const packagePath = path.join(PACKAGE_DIR, "styles", `${name}.md`);
	try {
		return fs.readFileSync(packagePath, "utf8");
	} catch {
		return "";
	}
}

// ---------------------------------------------------------------------------
// Env block
// ---------------------------------------------------------------------------

function buildEnvBlock(state: SessionState): string {
	const user = process.env.USER || os.userInfo().username || "unknown";
	const lines: string[] = [
		`User: ${user}`,
		`Working directory: ${state.primaryDir}`,
	];

	if (state.worktreeDir) {
		lines.push(`Worktree directory: ${state.worktreeDir}`);
		if (state.worktreeBranch) {
			lines.push(`Worktree branch: ${state.worktreeBranch}`);
		}
		lines.push("");
		lines.push(
			"⚠ WORKTREE ACTIVE: All file operations (read, edit, write, bash) MUST target the " +
			"worktree directory using absolute paths. The working directory contains the main " +
			"branch checkout and must not be modified. Bash commands execute in the worktree " +
			"directory automatically.",
		);
	}

	if (state.secondaryDirs.length > 0) {
		lines.push(`Additional directories: ${state.secondaryDirs.join(", ")}`);
	}

	lines.push(`Is directory a git repo: ${state.isRepo ? "Yes" : "No"}`);

	if (state.remoteUrl) {
		lines.push(`Git remote: ${state.remoteUrl}`);
	}

	lines.push(`Platform: ${process.platform}`);

	const tz = getTimezone();
	const today = new Intl.DateTimeFormat("en-CA", {
		timeZone: tz ?? undefined,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).format(new Date());
	lines.push(`Today's date: ${today}`);

	lines.push(`Work directory: ${state.workDir}`);

	if (state.workingStyle !== "logseq") {
		const logseqGraph = getLogseqGraph();
		if (logseqGraph) {
			lines.push(`Logseq graph: ${logseqGraph}`);
		}
	}

	return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Git status snapshot
// ---------------------------------------------------------------------------

export interface GitStatusResult {
	branch: string | null;
	mainBranch: string;
	status: string;
	recentCommits: string;
}

function formatGitStatus(git: GitStatusResult): string {
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

// ---------------------------------------------------------------------------
// Full assembly
// ---------------------------------------------------------------------------

export interface AssembleOptions {
	state: SessionState;
	gitStatus: GitStatusResult | null;
}

/**
 * Assemble the basecamp prompt content to prepend before pi's default system prompt.
 *
 * Layer order:
 *   1. Env block (runtime context)
 *   2. environment.md (tool/environment guidelines)
 *   3. Git status snapshot
 *   4. Working style (engineering/advisor)
 *   5. system.md (working principles, task management)
 *   6. Project context (if configured)
 */
export function assemblePrompt(opts: AssembleOptions): string {
	const { state, gitStatus } = opts;

	const parts: string[] = [];

	// 1. Env block
	parts.push(buildEnvBlock(state));

	// 2. Environment guidelines
	const environment = loadPromptFile("environment.md").trim();
	if (environment) {
		parts.push(environment);
	}

	// 3. Git status
	if (gitStatus) {
		parts.push(formatGitStatus(gitStatus));
	}

	// 4. Working style
	const style = loadWorkingStyle(state.workingStyle).trim();
	if (style) {
		parts.push(style);
	}

	// 5. System prompt
	const system = loadPromptFile("system.md").trim();
	if (system) {
		parts.push(system);
	}

	// 6. Project context
	if (state.contextContent) {
		parts.push(`# Project Context\n\n${state.contextContent}`);
	}

	return parts.join("\n\n");
}

// ---------------------------------------------------------------------------
// Hook registration
// ---------------------------------------------------------------------------

export function registerPrompt(pi: ExtensionAPI): void {
	pi.on("before_agent_start", async (event, _ctx) => {
		const basecampPrompt = assemblePrompt({
			state: getState(),
			gitStatus: getGitStatus(),
		});

		return {
			systemPrompt: basecampPrompt + "\n\n" + event.systemPrompt,
		};
	});
}
