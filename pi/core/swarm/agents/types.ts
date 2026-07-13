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
// One uniform read-only toolset for every dispatched agent: subagents investigate,
// review, and report; the primary session is the sole mutator ("main does all edits").
// `write`/`edit` are withheld from every agent. `bash` stays (scouts need git log/gh,
// reviewers need git diff) and is deliberately NOT a mutation sandbox — true bash
// containment is the container-isolation direction (docs/design/agent-isolation.md).
export const AGENT_TOOLS = ["read", "bash", "grep", "find", "ls"] as const;

export function getAgentToolAllowlist(): string[] {
	return [...AGENT_TOOLS, ...SUBAGENT_SUPPORT_TOOLS];
}
