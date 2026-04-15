/**
 * Type definitions for the agent system.
 */

import { Type, type Static } from "@sinclair/typebox";

// ============================================================================
// Agent Definitions
// ============================================================================

/**
 * Model resolution strategy for an agent.
 *
 * - "inherit"  — use the spawning parent's current model
 * - "default"  — use pi's default model (no --model flag)
 * - string     — explicit model identifier (e.g. "anthropic/claude-haiku-4-5")
 */
export type ModelStrategy = "inherit" | "default" | (string & {});

export interface AgentConfig {
  name: string;
  description: string;
  model: ModelStrategy;
  thinking?: string;
  tools?: string[];
  skills?: string[];
  systemPrompt: string;
  source: "builtin" | "user" | "project";
  filePath: string;
}

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
  agentSource: "builtin" | "user" | "project" | "ad-hoc";
  task: string;
  exitCode: number;
  output: string;
  error?: string;
  model?: string;
  toolCalls: ToolCallRecord[];
  usage: UsageStats;
  durationMs: number;
}

// ============================================================================
// Tool Schema
// ============================================================================

export const AgentToolParams = Type.Object({
  agent: Type.Optional(Type.String({ description: "Agent definition name" })),
  task: Type.String({ description: "Task description" }),
  model: Type.Optional(Type.String({ description: "Override model (only honoured for agents with model: inherit)" })),
  name: Type.Optional(Type.String({ description: "Name suffix (auto-generated prefix)" })),
});

export type AgentToolInput = Static<typeof AgentToolParams>;

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_AGENT_MAX_DEPTH = 2;
