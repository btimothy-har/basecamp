import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getAgentDepth } from "../../host/env.ts";
import { isWithin } from "../../host/paths.ts";
import { resolveDaemonPaths } from "../../hub/index.ts";
import type { AgentWorkspaceProvision } from "./agent-workspace.ts";
import type { AgentConfig } from "./discovery.ts";
import { buildAgentRunName, buildPiArgs, type RunWorkspace, sanitizeAgentSpawnEnv } from "./executor.ts";
import { resolveModel } from "./model-resolution.ts";
import { DEFAULT_AGENT_MAX_DEPTH } from "./types.ts";

// Top-level-only extension tools — excluded from every dispatched agent's toolset so a
// subagent never sees a tool it could only hit a hard guard on. `agent`/`escalate` are
// dispatch/UI-only; `report_findings` is primary-only (guarded in pi/code-review/tools.ts).
const SUBAGENT_EXCLUDED_EXTENSION_TOOLS = new Set(["agent", "escalate", "report_findings"]);

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
	// When the caller already resolved the requested agent, pass it to avoid a second
	// discoverAgents() scan (`undefined` ⇒ resolve here; `null` ⇒ resolved-but-unknown).
	resolvedAgent?: AgentConfig | null;
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
	// The run's provisioned workspace. Required for a repo-backed session (fail-closed: a
	// write-capable agent must never share the parent's tree); null only when the session
	// has no repo. The agent spawns with cwd inside it and auto-adopts it on startup.
	agentWorkspace: AgentWorkspaceProvision | null;
}

export interface SharedAgentLaunchPlan {
	agent: AgentConfig | null;
	agentLabel: string;
	model: string | undefined;
	name: string;
	environment: Record<string, string>;
	extensionTools: string[];
	spawnCwd: string;
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

function fallbackSpawnCwd(workspace: LaunchWorkspaceState | null): string {
	return workspace?.launchCwd ?? process.cwd();
}

function resolveSessionDir(agentId: string): string {
	return path.join(resolveDaemonPaths().agentsDir, agentId, "session");
}

/**
 * The parent-session identity stamped on a dispatched agent: the explicit
 * BASECAMP_SESSION_NAME, else the live session name (an empty one ignored), else
 * the session id. Shared by dispatch/ask so the empty-name fallthrough is
 * consistent: the `||` drops an empty trimmed name (an earlier `??` would keep
 * it), which is the intended behaviour.
 */
export function resolveParentSession(
	pi: { getSessionName(): string | undefined },
	ctx: { sessionManager: { getSessionId(): string } },
): string {
	return process.env.BASECAMP_SESSION_NAME ?? (pi.getSessionName()?.trim() || ctx.sessionManager.getSessionId());
}

export function buildAgentEnv(opts: { name: string; parentSession: string; project: string }): Record<string, string> {
	const depth = getAgentDepth();
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
	return isWithin(sourcePath, basecampExtensionRoot);
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
	const agent =
		input.resolvedAgent !== undefined
			? input.resolvedAgent
			: requested
				? (input.getAgents().find((candidate) => candidate.name === requested) ?? null)
				: null;
	if (requested && !agent) {
		const available =
			input
				.getAgents()
				.map((a) => a.name)
				.join(", ") || "none";
		return {
			ok: false,
			agentLabel: requested,
			message: `Unknown agent: ${requested}. Available: ${available}`,
		};
	}

	// Fail-closed: every repo-backed dispatch runs in its own provisioned workspace. A
	// write-capable agent must never fall back to sharing the parent's tree.
	const repoBacked = Boolean(input.workspace?.repo?.root);
	if (repoBacked && !input.agentWorkspace) {
		return {
			ok: false,
			agentLabel: agent?.name ?? "ad-hoc",
			message: `Agent "${agent?.name ?? "ad-hoc"}" requires a provisioned workspace in a repo-backed session; none was supplied.`,
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
	// Stamp the child env with the agent's own workspace so pre-adoption daemon identity
	// never reflects the parent's worktree.
	if (input.agentWorkspace) {
		environment.BASECAMP_WORKTREE_DIR = input.agentWorkspace.worktreeDir;
		environment.BASECAMP_WORKTREE_LABEL = input.agentWorkspace.label;
	}
	const extensionTools = getBasecampExtensionToolNames(input.pi, input.basecampExtensionRoot);
	// The agent spawns inside its own workspace (auto-adopted via isLinkedWorktree); only a
	// non-repo session runs at the launch cwd with no workspace — and, per capability-follows-
	// workspace, without structured mutation tools.
	const spawnCwd = input.agentWorkspace?.worktreeDir ?? fallbackSpawnCwd(input.workspace);
	const runWorkspace: RunWorkspace = input.agentWorkspace
		? input.agentWorkspace.kind === "deliverable"
			? { kind: "deliverable", branch: input.agentWorkspace.branch }
			: { kind: input.agentWorkspace.kind }
		: null;

	const sessionDir = resolveSessionDir(input.agentId);
	const { args, agentDir } = buildPiArgs(agent, input.task, {
		name,
		model,
		sessionDir,
		sessionId: input.agentId,
		extensionTools,
		workspace: runWorkspace,
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
			spawnCwd,
			sessionDir,
			sessionId: input.agentId,
			args,
			agentDir,
		},
	};
}
