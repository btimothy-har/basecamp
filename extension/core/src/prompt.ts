/**
 * Prompt Assembly — builds the complete basecamp system prompt.
 *
 * Fully replaces pi's default system prompt via the before_agent_start
 * hook. Tools and skills are sourced dynamically from pi's APIs
 * (getAllTools, getCommands) so we don't lose those sections.
 *
 * Reads bundled prompt files (environment.md, working styles) and assembles
 * them with runtime context (env block, git status).
 *
 * User overrides in ~/.basecamp/prompts/ take precedence over bundled defaults.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getLogseqGraph, getTimezone, type SessionState } from "../../config";
import {
	buildGitContext,
	buildProjectContext,
	buildSkillsContext,
	buildToolsContext,
	buildWorktreeWarning,
	type ContextFile,
	discoverContextFiles,
	type GitStatus,
	type SkillInfo,
	type ToolInfo,
} from "../../context";
import { getGitStatus, getState } from "./session";

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

export function loadPromptFile(filename: string): string {
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
	const tz = getTimezone();
	const today = new Intl.DateTimeFormat("en-CA", {
		timeZone: tz ?? undefined,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).format(new Date());

	const lines: string[] = [
		`User: ${user}`,
		`Platform: ${process.platform}`,
		`Today's date: ${today}`,
		"",
		`Working directory: ${state.primaryDir}`,
		`Is directory a git repo: ${state.isRepo ? "Yes" : "No"}`,
	];

	if (state.remoteUrl) {
		lines.push(`Git remote: ${state.remoteUrl}`);
	}

	const worktreeWarning = buildWorktreeWarning(state);
	if (worktreeWarning) {
		lines.push(worktreeWarning);
	}

	if (state.secondaryDirs.length > 0) {
		lines.push("");
		lines.push("Other directories:");
		for (const dir of state.secondaryDirs) {
			lines.push(`- ${dir}`);
		}
	}

	return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Full assembly
// ---------------------------------------------------------------------------

export interface AssembleOptions {
	state: SessionState;
	gitStatus: GitStatus | null;
	tools: ToolInfo[];
	skills: SkillInfo[];
	contextFiles: ContextFile[];
	/** Agent prompt — when set, replaces working style (worker mode) */
	agentPrompt?: string;
}

/**
 * Assemble the complete basecamp system prompt.
 *
 * This fully replaces pi's default system prompt. Tools, skills,
 * and context files are sourced dynamically so we control placement.
 *
 * Layer order:
 *   1. Env block (user, platform, directories)
 *   2. environment.md (tool/environment guidelines, scratch dir)
 *   3. Working style — OR agent prompt (workers)
 *   4. Logseq graph (conditional — when configured, non-logseq style)
 *   5. Available tools + skills
 *   6. Project context (basecamp context + CLAUDE.md/AGENTS.md)
 *   7. Git status snapshot
 */
export function assemblePrompt(opts: AssembleOptions): string {
	const { state, gitStatus, tools, skills, contextFiles } = opts;

	const parts: string[] = [];

	// 1. Env block
	parts.push(buildEnvBlock(state));

	// 2. Environment guidelines
	let environment = loadPromptFile("environment.md").trim();
	if (environment) {
		environment = environment.replaceAll("{{SCRATCH_DIR}}", state.scratchDir);
		parts.push(environment);
	}

	// 3. Working style — OR agent prompt (workers)
	if (opts.agentPrompt) {
		parts.push(opts.agentPrompt);
	} else {
		const style = loadWorkingStyle(state.workingStyle).trim();
		if (style) {
			parts.push(style);
		}
	}

	// 4. Logseq graph (when configured and not in logseq working style)
	if (state.workingStyle !== "logseq") {
		const logseqGraph = getLogseqGraph();
		if (logseqGraph) {
			let logseq = loadPromptFile("logseq.md").trim();
			if (logseq) {
				logseq = logseq.replaceAll("{{LOGSEQ_GRAPH}}", logseqGraph);
				parts.push(logseq);
			}
		}
	}

	// 5. Available tools + skills
	const toolsBlock = buildToolsContext(tools);
	if (toolsBlock) {
		parts.push(toolsBlock);
	}
	const skillsBlock = buildSkillsContext(skills);
	if (skillsBlock) {
		parts.push(skillsBlock);
	}

	// 6. Project context (basecamp context + CLAUDE.md/AGENTS.md)
	const projectContext = buildProjectContext(state, contextFiles);
	if (projectContext) {
		parts.push(projectContext);
	}

	// 7. Git status
	if (gitStatus) {
		parts.push(buildGitContext(gitStatus));
	}

	return parts.join("\n\n");
}

// ---------------------------------------------------------------------------
// Hook registration
// ---------------------------------------------------------------------------

/** Pi's default system prompt starts with this prefix. If the prompt doesn't
 *  match, --system-prompt was explicitly passed and we should respect it. */
const PI_DEFAULT_PREFIX = "You are an expert coding assistant";

export function registerPrompt(pi: ExtensionAPI): void {
	pi.on("before_agent_start", async (event, ctx) => {
		if (!event.systemPrompt.startsWith(PI_DEFAULT_PREFIX)) {
			return;
		}

		const state = getState();

		// Collect active tools from pi
		const activeNames = new Set(pi.getActiveTools());
		const tools = pi
			.getAllTools()
			.filter((t) => activeNames.has(t.name))
			.map((t) => ({ name: t.name, description: t.description }));

		// Collect skills from pi
		const skills = pi
			.getCommands()
			.filter((c) => c.source === "skill")
			.map((c) => ({
				name: c.name,
				description: c.description,
				sourceInfo: c.sourceInfo,
			}));

		// Discover CLAUDE.md / AGENTS.md from cwd
		const contextFiles = discoverContextFiles(ctx.cwd);

		// Agent prompt: replaces working style for workers
		const agentPromptFile = pi.getFlag("agent-prompt") as string | undefined;
		let agentPrompt: string | undefined;
		if (agentPromptFile) {
			try {
				agentPrompt = fs.readFileSync(agentPromptFile, "utf-8").trim();
			} catch {
				// File not found or unreadable — fall through to normal prompt
			}
		}

		const prompt = assemblePrompt({
			state,
			gitStatus: getGitStatus(),
			tools,
			skills,
			contextFiles,
			agentPrompt,
		});

		// Fully replace pi's default system prompt
		return { systemPrompt: prompt };
	});
}
