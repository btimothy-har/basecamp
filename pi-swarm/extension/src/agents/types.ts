/**
 * Type definitions for the agent system.
 */

import { type Static, Type } from "@sinclair/typebox";
import type { TaskProgressSnapshot } from "../dependencies.ts";
import type { AgentConfig } from "./discovery.ts";

// Re-export agent discovery types so runtime modules have one import surface.
export type { AgentConfig, ModelStrategy } from "./discovery.ts";

// ============================================================================
// Tool Result Details (for renderResult)
// ============================================================================

export interface ToolCallRecord {
	name: string;
	args: Record<string, unknown>;
}

export interface UsageStats {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
	turns: number;
}

export interface AgentDetails {
	agent: string;
	agentSource: "builtin" | "ad-hoc";
	task: string;
	exitCode: number;
	output: string;
	error?: string;
	model?: string;
	toolCalls: ToolCallRecord[];
	usage: UsageStats;
	durationMs: number;
	taskProgress?: TaskProgressSnapshot;
}

/** Partial details emitted during agent execution via onUpdate. */
export interface AgentPartialDetails {
	agent: string;
	agentSource: "builtin" | "ad-hoc";
	model?: string;
	toolCalls: ToolCallRecord[];
	turnCount: number;
	taskProgress?: TaskProgressSnapshot;
	/** Latest assistant message text (intermediate, not final). */
	latestMessage?: string;
}

// ============================================================================
// Tool Schema
// ============================================================================

export const AgentToolParams = Type.Object({
	agent: Type.Optional(Type.String({ description: "Agent definition name" })),
	task: Type.String({ description: "Task description" }),
	name: Type.Optional(Type.String({ description: "Name suffix (auto-generated prefix)" })),
});

export type AgentToolInput = Static<typeof AgentToolParams>;

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_AGENT_MAX_DEPTH = 2;

// ============================================================================
// Agent Tool Policy
// ============================================================================

export const MUTATIVE_AGENT_NAME = "worker";
export const READ_ONLY_AGENT_TOOLS = ["read", "bash", "grep", "find", "ls"] as const;
export const MUTATIVE_AGENT_TOOLS = ["read", "write", "edit", "bash", "grep", "find", "ls"] as const;

export type AgentRunKind = "named-read-only" | "mutative" | "ad-hoc";

export function getAgentRunKind(agentConfig: AgentConfig | null): AgentRunKind {
	if (!agentConfig) return "ad-hoc";
	return agentConfig.name === MUTATIVE_AGENT_NAME ? "mutative" : "named-read-only";
}

export function getAgentToolAllowlist(agentConfig: AgentConfig | null): string[] {
	return [...(getAgentRunKind(agentConfig) === "mutative" ? MUTATIVE_AGENT_TOOLS : READ_ONLY_AGENT_TOOLS)];
}
