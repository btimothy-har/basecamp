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
 * User overrides in ~/.pi/prompts/ (and ~/.pi/styles/, ~/.pi/languages/) take
 * precedence over bundled defaults.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getLanguage, getLogseqGraph, getTimezone, type SessionState } from "../../config";
import {
	buildCapabilitiesIndex,
	buildGitContext,
	buildProjectContext,
	buildWorktreeWarning,
	type ContextFile,
	discoverContextFiles,
	type GitStatus,
} from "../../context";
import { discoverAgents } from "../../discovery";
import { getGitStatus, getState } from "./session";

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

/** Bundled prompt files shipped with the extension package. */
const PACKAGE_DIR = path.resolve(__dirname, "system-prompts");

/** User overrides — checked first before falling back to package defaults. */
const USER_PROMPTS_DIR = path.join(os.homedir(), ".pi", "prompts");
const USER_STYLES_DIR = path.join(os.homedir(), ".pi", "styles");
const USER_LANGUAGES_DIR = path.join(os.homedir(), ".pi", "languages");

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

function loadLanguagePrompt(name: string): string {
	// Check user override
	const userPath = path.join(USER_LANGUAGES_DIR, `${name}.md`);
	try {
		return fs.readFileSync(userPath, "utf8");
	} catch {
		// Fall through to package default
	}

	const packagePath = path.join(PACKAGE_DIR, "languages", `${name}.md`);
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
	toolNames: string[];
	skillNames: string[];
	agentNames: string[];
	contextFiles: ContextFile[];
	/** Agent prompt — when set, replaces working style (worker mode) */
	agentPrompt?: string;
	/** Model ID (e.g. "claude-sonnet-4-20250514") */
	modelId?: string;
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
 *   3. Logseq graph (conditional — when configured, non-logseq style)
 *   4. Working style — OR agent prompt (subagents)
 *   4b. Language (interactive sessions only)
 *   5. Available tools + skills
 *   6. Project context (basecamp context + CLAUDE.md/AGENTS.md)
 *   7. Git status snapshot
 */
export function assemblePrompt(opts: AssembleOptions): string {
	const { state, gitStatus, toolNames, skillNames, agentNames, contextFiles, modelId } = opts;

	const parts: string[] = [];

	// 1. Env block
	parts.push(buildEnvBlock(state));

	// 2. Environment guidelines
	let environment = loadPromptFile("environment.md").trim();
	if (environment) {
		environment = environment.replaceAll("{{SCRATCH_DIR}}", state.scratchDir);
		environment = environment.replaceAll("{{MODEL_NAME}}", modelId ?? "an AI assistant");
		parts.push(environment);
	}

	// 3. Logseq graph (when configured and not in logseq working style)
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

	// 4. Working style — OR agent prompt (subagents)
	if (opts.agentPrompt) {
		parts.push(opts.agentPrompt);
	} else {
		const style = loadWorkingStyle(state.workingStyle).trim();
		if (style) {
			parts.push(style);
		}

		// 4b. Language (interactive sessions only — skipped for agents)
		const languageName = getLanguage();
		if (languageName) {
			const lang = loadLanguagePrompt(languageName).trim();
			if (lang) {
				parts.push(lang);
			}
		}
	}

	// 5. Capabilities index (names only + discover tool instructions)
	parts.push(
		buildCapabilitiesIndex({
			toolNames,
			skillNames,
			agentNames,
			includeAgents: !opts.agentPrompt,
		}),
	);

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

		// Collect active tool names
		const activeNames = new Set(pi.getActiveTools());
		const toolNames = pi
			.getAllTools()
			.filter((t) => activeNames.has(t.name))
			.map((t) => t.name);

		// Collect skill names
		const skillNames = pi
			.getCommands()
			.filter((c) => c.source === "skill")
			.map((c) => c.name.replace(/^skill:/, ""));

		// Discover CLAUDE.md / AGENTS.md from cwd
		const contextFiles = discoverContextFiles(ctx.cwd);

		// Discover available agent names
		const agentNames = discoverAgents(ctx.cwd).map((a) => a.name);

		// Agent prompt: replaces working style for subagents
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
			toolNames,
			skillNames,
			agentNames,
			contextFiles,
			agentPrompt,
			modelId: ctx.model?.id,
		});

		// Fully replace pi's default system prompt
		return { systemPrompt: prompt };
	});
}
