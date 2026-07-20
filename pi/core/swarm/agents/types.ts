/**
 * Type definitions for the agent system.
 */

import { getAgentDepth } from "../../host/env.ts";
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
	const depth = getAgentDepth();
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
	"delete_task",
] as const;
export const SUBAGENT_SUPPORT_TOOLS = ["skill", ...TASK_TRACKING_TOOLS, "bq_query"] as const;
// The read-only toolset for a dispatched agent: subagents investigate, review, and
// report; `write`/`edit` are withheld. `bash` stays (scouts need git log/gh, reviewers
// need git diff). Read-only agents share the parent's worktree and see live WIP.
export const AGENT_TOOLS = ["read", "bash", "grep", "find", "ls"] as const;

// A mutative agent additionally gets `write`/`edit`. It is confined to its OWN worktree
// (branched from the parent's HEAD), commits its branch, and the parent integrates it by
// merge — the worktree is the boundary, not a shared sandbox (docs/design/agent-isolation.md).
export const MUTATIVE_AGENT_TOOLS = ["write", "edit"] as const;

export function getAgentToolAllowlist(): string[] {
	return [...AGENT_TOOLS, ...SUBAGENT_SUPPORT_TOOLS];
}

export function getMutativeAgentToolAllowlist(): string[] {
	return [...AGENT_TOOLS, ...MUTATIVE_AGENT_TOOLS, ...SUBAGENT_SUPPORT_TOOLS];
}
