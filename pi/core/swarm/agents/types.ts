/**
 * Type definitions for the agent system.
 */

import { getAgentDepth } from "../../host/env.ts";

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
// The uniform toolset for every dispatched agent WITH a workspace: each run works in its
// own transient worktree, so `write`/`edit` are safe — the workspace is the isolation
// boundary, not the toolset. `bash` is not a mutation sandbox; worktree confinement holds.
export const AGENT_TOOLS = ["read", "write", "edit", "bash", "grep", "find", "ls"] as const;
// Capability follows workspace: a run with no provisioned workspace (non-repo session) has
// no wall, so structured mutation tools are withheld.
const WORKSPACELESS_EXCLUDED = new Set(["write", "edit"]);

export function getAgentToolAllowlist(): string[] {
	return [...AGENT_TOOLS, ...SUBAGENT_SUPPORT_TOOLS];
}

export function getWorkspacelessAgentToolAllowlist(): string[] {
	return getAgentToolAllowlist().filter((tool) => !WORKSPACELESS_EXCLUDED.has(tool));
}
