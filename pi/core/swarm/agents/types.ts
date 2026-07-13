/**
 * Type definitions for the agent system.
 */

import type { AgentConfig } from "./discovery.ts";

// Re-export agent discovery types so runtime modules have one import surface.
export type { AgentConfig, ModelStrategy } from "./discovery.ts";

export const DEFAULT_AGENT_MAX_DEPTH = 2;

export interface AgentDepthState {
	depth: number;
	isTopLevel: boolean;
	maxDepth: number;
	atMaxDepth: boolean;
}

/** Resolve this process's agent-depth gating from BASECAMP_AGENT_DEPTH / BASECAMP_AGENT_MAX_DEPTH. */
export function resolveAgentDepthState(): AgentDepthState {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	const isTopLevel = Number.isFinite(depth) ? depth <= 0 : true;
	const maxDepth = Number(process.env.BASECAMP_AGENT_MAX_DEPTH ?? DEFAULT_AGENT_MAX_DEPTH);
	const atMaxDepth = depth >= maxDepth;
	return { depth, isTopLevel, maxDepth, atMaxDepth };
}

export const TASK_TRACKING_TOOLS = [
	"update_goal",
	"create_tasks",
	"start_task",
	"complete_task",
	"get_task",
	"annotate_task",
	"delete_task",
] as const;
export const SUBAGENT_SUPPORT_TOOLS = ["skill", ...TASK_TRACKING_TOOLS, "bq_query"] as const;
// One unified, write-capable toolset for every dispatched agent: the
// mutative/read-only-by-persona distinction (and its guards) is retired.
export const AGENT_TOOLS = ["read", "write", "edit", "bash", "grep", "find", "ls"] as const;

export function getAgentToolAllowlist(): string[] {
	return [...AGENT_TOOLS, ...SUBAGENT_SUPPORT_TOOLS];
}
