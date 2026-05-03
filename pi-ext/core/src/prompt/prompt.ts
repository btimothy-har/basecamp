/**
 * Prompt Assembly — builds the complete basecamp system prompt.
 *
 * Fully replaces pi's default system prompt via the before_agent_start
 * hook. Tools and skills are sourced dynamically from pi's APIs
 * (getAllTools, getCommands) so we don't lose those sections.
 *
 * Reads bundled prompt files (environment.md, working styles) and assembles
 * them with runtime context (env block).
 *
 * User overrides in ~/.pi/prompts/ (and ~/.pi/styles/, ~/.pi/languages/) take
 * precedence over bundled defaults.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type CatalogItem, listCatalogItemsByType } from "../../../platform/catalog";
import { type BasecampProjectState, getLanguage, getLogseqGraph, getTimezone } from "../../../platform/config";
import {
	buildCapabilitiesIndex,
	buildProjectContext,
	buildWorktreeWarning,
	type ContextFile,
	discoverContextFiles,
} from "../../../platform/context";
import { getBasecampProjectState } from "../../../platform/project";
import { getWorkspaceService, getWorkspaceState, type WorkspaceState } from "../../../platform/workspace";
import { getAgentMode } from "../runtime/mode";

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

function getPromptEffectiveCwd(workspace: WorkspaceState | null = getWorkspaceState()): string {
	const service = getWorkspaceService();
	if (service && workspace) {
		try {
			return service.getEffectiveCwd();
		} catch {
			// Fall through to state/process fallback
		}
	}
	return workspace?.effectiveCwd ?? process.cwd();
}

function buildEnvBlock(
	workspace: WorkspaceState | null,
	project: BasecampProjectState | null,
	effectiveCwd: string,
	modelId?: string,
): string {
	const user = process.env.USER || os.userInfo().username || "unknown";
	const tz = getTimezone();
	const today = new Intl.DateTimeFormat("en-CA", {
		timeZone: tz ?? undefined,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).format(new Date());

	const modelName = modelId ?? "an AI assistant";
	const repo = workspace?.repo ?? null;
	const activeWorktree = workspace?.activeWorktree ?? null;
	const protectedRoot = workspace?.protectedRoot ?? repo?.root ?? null;
	const lines: string[] = [
		`You are ${modelName}. You are operating inside pi-coding-agent, a terminal based AI harness.`,
		"",
		`User: ${user}`,
		`Platform: ${process.platform}`,
		`Today's date: ${today}`,
		"",
	];

	if (activeWorktree) {
		const branch = activeWorktree.branch ? `, branch: ${activeWorktree.branch}` : "";
		lines.push(`Working directory: ${effectiveCwd} (active worktree: ${activeWorktree.label}${branch})`);
		if (protectedRoot) lines.push(`Protected repository checkout: ${protectedRoot}`);
	} else if (repo?.isRepo) {
		lines.push(`Working directory: ${effectiveCwd} (protected repository checkout; no active worktree)`);
		if (protectedRoot && path.resolve(effectiveCwd) !== path.resolve(protectedRoot)) {
			lines.push(`Protected repository checkout: ${protectedRoot}`);
		}
	} else {
		lines.push(`Working directory: ${effectiveCwd}`);
	}

	const worktreeWarning = buildWorktreeWarning(workspace);
	if (worktreeWarning) {
		lines.push("", worktreeWarning, "");
	}

	lines.push(`Is directory a git repo: ${repo?.isRepo ? "Yes" : "No"}`);

	if (repo?.remoteUrl) {
		lines.push(`Git remote: ${repo.remoteUrl}`);
	}

	const additionalDirs = project?.additionalDirs ?? [];
	if (additionalDirs.length > 0) {
		lines.push("");
		lines.push("Other directories:");
		for (const dir of additionalDirs) {
			lines.push(`- ${dir}`);
		}
	}

	lines.push("");
	lines.push(`Scratch directory: ${workspace?.scratchDir ?? path.join("/tmp", "pi", path.basename(effectiveCwd))}`);

	return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Full assembly
// ---------------------------------------------------------------------------

export interface AssembleOptions {
	workspace: WorkspaceState | null;
	project: BasecampProjectState | null;
	effectiveCwd: string;
	toolItems: CatalogItem[];
	skillItems: CatalogItem[];
	agentItems: CatalogItem[];
	contextFiles: ContextFile[];
	/** Agent prompt — when set, replaces primary-session posture and working style */
	agentPrompt?: string;
	readOnly?: boolean;
	/** Model ID (e.g. "claude-sonnet-4-20250514") */
	modelId?: string;
}

/**
 * Assemble the complete basecamp system prompt.
 *
 * This fully replaces pi's default system prompt. Tools, skills,
 * and context files are sourced dynamically so we control placement.
 *
 * Session mode overlays are placed first so operating constraints lead.
 * Remaining layers are ordered static → semi-static → dynamic to maximize
 * prefix caching where possible.
 *
 * Layer order:
 *   0. Read-only overlay (when --read-only is set)
 *   1. Session mode overlay: analysis, planning, supervisor, or executor (primary sessions only)
 *   2. Working style — OR agent prompt (static per user/agent)
 *   2b. Language (static per user, interactive sessions only)
 *   3. environment.md (static — tool/environment guidelines)
 *   4. Logseq graph (semi-static — conditional, path rarely changes)
 *   5. Capabilities index (semi-static — tool/skill/agent names and descriptions)
 *   6. Project context (semi-static — changes per project)
 *   7. Env block (dynamic — identity, user, platform, date, dirs)
 */
export function assemblePrompt(opts: AssembleOptions): string {
	const { workspace, project, effectiveCwd, toolItems, skillItems, agentItems, contextFiles, modelId } = opts;
	const workingStyle = project?.workingStyle ?? "engineering";

	const parts: string[] = [];

	if (opts.readOnly) {
		const readOnly = loadPromptFile("modes/read-only.md").trim();
		if (readOnly) {
			parts.push(readOnly);
		}
	}

	// 1. Session mode overlay (primary sessions only — skipped for agents)
	if (!opts.agentPrompt) {
		const posture = loadPromptFile(`modes/${getAgentMode()}.md`).trim();
		if (posture) {
			parts.push(posture);
		}
	}

	// 2. Working style — OR agent prompt (subagents)
	if (opts.agentPrompt) {
		parts.push(opts.agentPrompt);
	} else {
		const style = loadWorkingStyle(workingStyle).trim();
		if (style) {
			parts.push(style);
		}

		// 2b. Language (interactive sessions only — skipped for agents)
		const languageName = getLanguage();
		if (languageName) {
			const lang = loadLanguagePrompt(languageName).trim();
			if (lang) {
				parts.push(lang);
			}
		}
	}

	// 3. Environment guidelines (fully static — no template substitutions)
	const environment = loadPromptFile("environment.md").trim();
	if (environment) {
		parts.push(environment);
	}

	// 4. Logseq graph (when configured and not in logseq working style)
	if (workingStyle !== "logseq") {
		const logseqGraph = getLogseqGraph();
		if (logseqGraph) {
			let logseq = loadPromptFile("logseq.md").trim();
			if (logseq) {
				logseq = logseq.replaceAll("{{LOGSEQ_GRAPH}}", logseqGraph);
				parts.push(logseq);
			}
		}
	}

	// 5. Capabilities index (names and descriptions)
	parts.push(
		buildCapabilitiesIndex({
			toolItems,
			skillItems,
			agentItems,
			includeAgents: !opts.agentPrompt,
		}),
	);

	// 6. Project context (basecamp context + CLAUDE.md/AGENTS.md)
	const projectContext = buildProjectContext(project, contextFiles);
	if (projectContext) {
		parts.push(projectContext);
	}

	// 7. Env block (dynamic — identity, user, platform, date, directories, scratch dir)
	parts.push(buildEnvBlock(workspace, project, effectiveCwd, modelId));

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

		const workspace = getWorkspaceState();
		const project = getBasecampProjectState();
		const effectiveCwd = getPromptEffectiveCwd(workspace);

		const catalogContext = { cwd: effectiveCwd };
		const toolItems = listCatalogItemsByType("tools", catalogContext);
		const skillItems = listCatalogItemsByType("skills", catalogContext);
		const agentItems = listCatalogItemsByType("agents", catalogContext);

		// Discover CLAUDE.md / AGENTS.md from effective cwd
		const contextFiles = discoverContextFiles(effectiveCwd);

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
			workspace,
			project,
			effectiveCwd,
			toolItems,
			skillItems,
			agentItems,
			contextFiles,
			agentPrompt,
			readOnly: pi.getFlag("read-only") === true,
			modelId: ctx.model?.id,
		});

		// Fully replace pi's default system prompt
		return { systemPrompt: prompt };
	});
}
