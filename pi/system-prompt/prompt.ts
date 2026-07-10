import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isCopilotMode, PLAN_TOOL_NAME } from "#core/agent-mode/copilot.ts";
import { getAgentMode } from "#core/agent-mode/index.ts";
import { type CatalogItem, listCatalogItemsByType } from "#core/catalog/index.ts";
import { type ContextFile, discoverContextFiles } from "#core/project/context.ts";
import { buildRepoLogseqContext } from "#core/project/logseq.ts";
import { getProjectState, type ProjectState } from "#core/project/project.ts";
import { getWorkspaceEffectiveCwd, getWorkspaceState, type WorkspaceState } from "#core/project/workspace/state.ts";
import {
	buildCapabilitiesIndex,
	buildProjectContext,
	buildUnsafeEditGuidance,
	buildWorktreeWarning,
} from "./context-builders.ts";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_DIR = path.resolve(MODULE_DIR, "defaults");
function getBasecampWorkspaceDir(): string {
	return path.join(os.homedir(), ".pi", "basecamp", "workspace");
}

function getUserPromptsDir(): string {
	return path.join(getBasecampWorkspaceDir(), "prompts");
}

function getUserStylesDir(): string {
	return path.join(getBasecampWorkspaceDir(), "styles");
}

export function loadPromptFile(filename: string): string {
	try {
		return fs.readFileSync(path.join(getUserPromptsDir(), filename), "utf8");
	} catch {}

	try {
		return fs.readFileSync(path.join(PACKAGE_DIR, filename), "utf8");
	} catch {
		return "";
	}
}

function loadWorkingStyle(name: string): string {
	try {
		return fs.readFileSync(path.join(getUserStylesDir(), `${name}.md`), "utf8");
	} catch {}

	try {
		return fs.readFileSync(path.join(PACKAGE_DIR, "styles", `${name}.md`), "utf8");
	} catch {
		return "";
	}
}

function formatToday(): string {
	return new Intl.DateTimeFormat("en-CA", {
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	}).format(new Date());
}

function buildEnvBlock(
	workspace: WorkspaceState | null,
	project: ProjectState | null,
	effectiveCwd: string,
	modelId?: string,
): string {
	const user = process.env.USER || os.userInfo().username || "unknown";
	const modelName = modelId ?? "an AI assistant";
	const repo = workspace?.repo ?? null;
	const activeWorktree = workspace?.activeWorktree ?? null;
	const protectedRoot = workspace?.protectedRoot ?? repo?.root ?? null;
	const lines: string[] = [
		`You are ${modelName}. You are operating inside pi-coding-agent, a terminal based AI harness.`,
		"",
		`User: ${user}`,
		`Platform: ${process.platform}`,
		`Today's date: ${formatToday()}`,
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
	} else {
		const unsafeEditGuidance = buildUnsafeEditGuidance(workspace);
		if (unsafeEditGuidance) lines.push("", unsafeEditGuidance, "");
	}

	lines.push(`Is directory a git repo: ${repo?.isRepo ? "Yes" : "No"}`);
	if (repo?.remoteUrl) lines.push(`Git remote: ${repo.remoteUrl}`);

	const additionalDirs = project?.additionalDirs ?? [];
	if (additionalDirs.length > 0) {
		lines.push("", "Other directories:");
		for (const dir of additionalDirs) lines.push(`- ${dir}`);
	}

	lines.push("", `Scratch directory: ${workspace?.scratchDir ?? path.join("/tmp", "pi", path.basename(effectiveCwd))}`);
	return lines.join("\n");
}

export interface AssembleOptions {
	workspace: WorkspaceState | null;
	project: ProjectState | null;
	effectiveCwd: string;
	toolItems: CatalogItem[];
	skillItems: CatalogItem[];
	agentItems: CatalogItem[];
	contextFiles: ContextFile[];
	agentPrompt?: string;
	readOnly?: boolean;
	modelId?: string;
}

export function assemblePrompt(opts: AssembleOptions): string {
	const { workspace, project, effectiveCwd, toolItems, skillItems, agentItems, contextFiles, modelId } = opts;
	const agentMode = getAgentMode();
	const workingStyle = project?.workingStyle ?? "engineering";
	const parts: string[] = [];

	if (opts.readOnly) {
		const readOnly = loadPromptFile("modes/read-only.md").trim();
		if (readOnly) parts.push(readOnly);
	}

	if (!opts.agentPrompt) {
		const posture = loadPromptFile(`modes/${agentMode}.md`).trim();
		if (posture) parts.push(posture);
	}

	if (opts.agentPrompt) {
		parts.push(opts.agentPrompt);
	} else if (agentMode !== "copilot") {
		const style = loadWorkingStyle(workingStyle).trim();
		if (style) parts.push(style);
	}

	const environment = loadPromptFile("environment.md").trim();
	if (environment) parts.push(environment);

	// Copilot is a locked, launch-only mode that stages work via launch_workstream and never implements in-session,
	// so plan() is hidden from its capabilities index (it is also hard-blocked at call time by pi-tasks).
	const capabilityToolItems = isCopilotMode(agentMode)
		? toolItems.filter((item) => item.name !== PLAN_TOOL_NAME)
		: toolItems;
	parts.push(
		buildCapabilitiesIndex({
			toolItems: capabilityToolItems,
			skillItems,
			agentItems,
			includeAgents: !opts.agentPrompt,
		}),
	);

	const projectContext = buildProjectContext(project, contextFiles);
	if (projectContext) parts.push(projectContext);

	if (agentMode === "copilot" && !opts.agentPrompt) {
		parts.push(buildRepoLogseqContext({ workspace }));
	}

	parts.push(buildEnvBlock(workspace, project, effectiveCwd, modelId));
	return parts.join("\n\n");
}

const PI_DEFAULT_PREFIX = "You are an expert coding assistant";

export function registerPrompt(pi: ExtensionAPI): void {
	pi.on("before_agent_start", async (event, ctx) => {
		if (!event.systemPrompt.startsWith(PI_DEFAULT_PREFIX)) return;

		const workspace = getWorkspaceState();
		const project = getProjectState();
		const effectiveCwd = getWorkspaceEffectiveCwd();
		const catalogContext = { cwd: effectiveCwd };
		const toolItems = listCatalogItemsByType("tools", catalogContext);
		const skillItems = listCatalogItemsByType("skills", catalogContext);
		const agentItems = listCatalogItemsByType("agents", catalogContext);
		const contextFiles = discoverContextFiles(effectiveCwd);
		const agentPromptFile = pi.getFlag("agent-prompt") as string | undefined;
		let agentPrompt: string | undefined;

		if (agentPromptFile) {
			try {
				agentPrompt = fs.readFileSync(agentPromptFile, "utf-8").trim();
			} catch {}
		}

		return {
			systemPrompt: assemblePrompt({
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
			}),
		};
	});
}
