/**
 * Type definitions for the agent system.
 */

import type { AgentConfig } from "./discovery.ts";

// Re-export agent discovery types so runtime modules have one import surface.
export type { AgentConfig, ModelStrategy } from "./discovery.ts";

export const DEFAULT_AGENT_MAX_DEPTH = 2;

export const MUTATIVE_AGENT_NAME = "worker";
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
export const READ_ONLY_AGENT_TOOLS = ["read", "bash", "grep", "find", "ls"] as const;
export const MUTATIVE_AGENT_TOOLS = ["read", "write", "edit", "bash", "grep", "find", "ls"] as const;

export type AgentRunKind = "named-read-only" | "mutative" | "ad-hoc";

export function getAgentRunKind(agentConfig: AgentConfig | null): AgentRunKind {
	if (!agentConfig) return "ad-hoc";
	return agentConfig.name === MUTATIVE_AGENT_NAME ? "mutative" : "named-read-only";
}

export function getAgentToolAllowlist(agentConfig: AgentConfig | null): string[] {
	const baseTools = getAgentRunKind(agentConfig) === "mutative" ? MUTATIVE_AGENT_TOOLS : READ_ONLY_AGENT_TOOLS;
	return [...baseTools, ...SUBAGENT_SUPPORT_TOOLS];
}
