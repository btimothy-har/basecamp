import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resolveDaemonPaths } from "../../hub/index.ts";
import type { AgentConfig } from "./discovery.ts";
import { buildAgentRunName, buildPiArgs, sanitizeAgentSpawnEnv } from "./executor.ts";
import { resolveModel } from "./model-resolution.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "./types.ts";

const SUBAGENT_EXCLUDED_EXTENSION_TOOLS = new Set(["agent", "escalate", "browser_eval", "browser_screenshot"]);

interface ToolInfo {
	name: string;
	sourceInfo: {
		source: string;
		baseDir: string;
		path: string;
	};
}

interface LaunchWorkspaceState {
	launchCwd?: string;
	activeWorktree?: {
		path: string;
	} | null;
	protectedRoot?: string | null;
	repo?: {
		root: string;
	} | null;
}

interface ParentModelContext {
	id: string;
	provider: string;
}

export interface SharedAgentLaunchInput {
	pi: ExtensionAPI;
	getAgents: () => AgentConfig[];
	basecampExtensionRoot: string;
	requestedAgent?: string;
	namePrefix: string;
	nameSuffix?: string;
	task: string;
	modelContext: ParentModelContext | undefined;
	resolveModelAlias: (model: string) => string | undefined;
	workspace: LaunchWorkspaceState | null;
	agentId: string;
	parentSession: string;
	project: string;
}

export interface SharedAgentLaunchPlan {
	agent: AgentConfig | null;
	agentLabel: string;
	model: string | undefined;
	name: string;
	environment: Record<string, string>;
	extensionTools: string[];
	spawnCwd: string;
	worktreeDir: string | null;
	sessionDir: string;
	sessionId?: string;
	args: string[];
	agentDir: string;
}

export interface SharedAgentLaunchFailure {
	ok: false;
	agentLabel: string;
	message: string;
}

export type SharedAgentLaunchResult = { ok: true; plan: SharedAgentLaunchPlan } | SharedAgentLaunchFailure;

function resolveWorkspaceSelection(workspace: LaunchWorkspaceState | null): {
	cwd: string;
	worktreeDir: string | null;
} {
	const fallback = process.cwd();
	return {
		cwd: workspace?.protectedRoot ?? workspace?.repo?.root ?? workspace?.launchCwd ?? fallback,
		worktreeDir: workspace?.activeWorktree?.path ?? null,
	};
}

function resolveSessionDir(agentId: string): string {
	return path.join(resolveDaemonPaths().agentsDir, agentId, "session");
}

export function buildAgentEnv(opts: { name: string; parentSession: string; project: string }): Record<string, string> {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const env: Record<string, string> = {};
	for (const [k, v] of Object.entries(process.env)) {
		if (k === "BASECAMP_AGENT_HANDLE") continue;
		if (k.startsWith("BASECAMP_") && v !== undefined) {
			env[k] = v;
		}
	}
	env.BASECAMP_PROJECT = opts.project;
	env.BASECAMP_PARENT_SESSION = opts.parentSession;
	env.BASECAMP_SIBLING_GROUP = opts.parentSession;
	env.BASECAMP_AGENT_DEPTH = String(depth + 1);
	env.BASECAMP_AGENT_MAX_DEPTH = process.env.BASECAMP_AGENT_MAX_DEPTH ?? String(DEFAULT_AGENT_MAX_DEPTH);
	return env;
}

function resolveToolSourcePath(value: string | undefined): string | null {
	if (!value || value.startsWith("<")) return null;
	try {
		return fs.realpathSync(value);
	} catch {
		return path.resolve(value);
	}
}

function isWithinBasecampExtensionRoot(value: string | undefined, basecampExtensionRoot: string): boolean {
	const sourcePath = resolveToolSourcePath(value);
	if (!sourcePath) return false;
	const relative = path.relative(basecampExtensionRoot, sourcePath);
	return relative === "" || (relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function isBasecampExtensionTool(tool: ToolInfo, basecampExtensionRoot: string): boolean {
	if (tool.sourceInfo.source === "builtin" || tool.sourceInfo.source === "sdk") return false;
	return (
		isWithinBasecampExtensionRoot(tool.sourceInfo.baseDir, basecampExtensionRoot) ||
		isWithinBasecampExtensionRoot(tool.sourceInfo.path, basecampExtensionRoot)
	);
}

export function getBasecampExtensionToolNames(pi: ExtensionAPI, basecampExtensionRoot: string): string[] {
	return pi
		.getAllTools()
		.filter(
			(tool) =>
				isBasecampExtensionTool(tool as ToolInfo, basecampExtensionRoot) &&
				!SUBAGENT_EXCLUDED_EXTENSION_TOOLS.has(tool.name),
		)
		.map((tool) => tool.name);
}

export function processEnvForSpawn(): Record<string, string> {
	const env: Record<string, string> = {};
	for (const [key, value] of Object.entries(process.env)) {
		if (typeof value === "string") env[key] = value;
	}
	return sanitizeAgentSpawnEnv(env);
}

export function buildAgentTitleBase(agentName: string | null | undefined, task: string): string {
	const prefix = agentName?.trim() ? agentName.trim() : "Agent";
	const compactTask = task.replace(/\s+/g, " ").trim();
	return `(${prefix}) ${compactTask.length > 56 ? `${compactTask.slice(0, 55).trimEnd()}…` : compactTask}`;
}

export function buildAgentLaunchSpec(input: SharedAgentLaunchInput): SharedAgentLaunchResult {
	const requested = input.requestedAgent || undefined;
	const agents = input.getAgents();
	const agent = requested ? (agents.find((candidate) => candidate.name === requested) ?? null) : null;
	if (requested && !agent) {
		return {
			ok: false,
			agentLabel: requested,
			message: `Unknown agent: ${requested}. Available: ${agents.map((a) => a.name).join(", ") || "none"}`,
		};
	}

	const model = resolveModel(agent?.model ?? "inherit", input.modelContext, {
		resolveModelAlias: input.resolveModelAlias,
	});

	const name = buildAgentRunName(input.namePrefix, input.nameSuffix);
	const environment = buildAgentEnv({
		name,
		parentSession: input.parentSession,
		project: input.project,
	});
	const extensionTools = getBasecampExtensionToolNames(input.pi, input.basecampExtensionRoot);
	const { cwd, worktreeDir } = resolveWorkspaceSelection(input.workspace);

	const sessionDir = resolveSessionDir(input.agentId);
	const { args, agentDir } = buildPiArgs(agent, input.task, {
		name,
		model,
		worktreeDir,
		sessionDir,
		sessionId: input.agentId,
		extensionTools,
	});

	return {
		ok: true,
		plan: {
			agent,
			agentLabel: requested || "ad-hoc",
			model,
			name,
			environment,
			extensionTools,
			spawnCwd: cwd,
			worktreeDir,
			sessionDir,
			sessionId: input.agentId,
			args,
			agentDir,
		},
	};
}
