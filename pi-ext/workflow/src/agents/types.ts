/**
 * Type definitions for the agent system.
 */

import { type Static, Type } from "@sinclair/typebox";
import type { TaskProgressSnapshot } from "../tasks/render";

// Re-export shared types so existing imports within workflow/src/agents still work.
export type { AgentConfig, ModelStrategy } from "../../../discovery.ts";

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
	agentSource: "builtin" | "user" | "ad-hoc";
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
	agentSource: "builtin" | "user" | "ad-hoc";
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
