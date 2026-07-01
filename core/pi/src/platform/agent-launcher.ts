import type { WorkspaceState } from "./workspace.ts";

/**
 * Process-scoped programmatic agent launcher registry.
 *
 * Agent implementations are owned by higher-level packages (for example
 * pi-swarm). Consumers such as pi-tasks depend only on this seam so core task
 * workflows do not import a concrete agent runtime.
 */

export interface AgentLaunchPi {
	getSessionName?(): string | null | undefined;
	getAllTools?(): readonly unknown[];
}

export interface AgentLaunchContext {
	model?: unknown;
	sessionManager: {
		getSessionId(): string;
	};
}

export interface AgentLaunchInput {
	pi: AgentLaunchPi;
	ctx: AgentLaunchContext;
	agent?: string;
	name?: string;
	task: string;
	workspace?: WorkspaceState | null;
	env?: Record<string, string>;
	title?: string;
}

export interface AgentLaunchSuccess {
	ok: true;
	agentHandle: string;
	agent: string;
}

export interface AgentLaunchFailure {
	ok: false;
	agent: string;
	message: string;
}

export type AgentLaunchResult = AgentLaunchSuccess | AgentLaunchFailure;

export interface AgentLauncher {
	id: string;
	launch(input: AgentLaunchInput): Promise<AgentLaunchResult>;
}

interface AgentLauncherRuntime {
	launcher: AgentLauncher | null;
}

const agentLauncherKey = Symbol.for("basecamp.agent-launcher");

type GlobalWithAgentLauncher = typeof globalThis & {
	[agentLauncherKey]?: AgentLauncherRuntime;
};

function getAgentLauncherRuntime(): AgentLauncherRuntime {
	const globalObject = globalThis as GlobalWithAgentLauncher;
	globalObject[agentLauncherKey] ??= { launcher: null };
	return globalObject[agentLauncherKey];
}

export function registerAgentLauncher(launcher: AgentLauncher): void {
	getAgentLauncherRuntime().launcher = launcher;
}

export function getAgentLauncher(): AgentLauncher | null {
	return getAgentLauncherRuntime().launcher;
}

export function clearAgentLauncherForTesting(): void {
	getAgentLauncherRuntime().launcher = null;
}
