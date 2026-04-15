/**
 * Type definitions for the agent/worker system.
 */

import { Type, type Static } from "@sinclair/typebox";

// ============================================================================
// Agent Definitions
// ============================================================================

/**
 * Model resolution strategy for a worker agent.
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
// Worker Tracking
// ============================================================================

export interface WorkerEntry {
  name: string;
  agent: string | null;
  status: "running" | "completed" | "failed";
  pid?: number;
  sessionDir?: string;
  model: string | undefined;
  task: string;
  createdAt: number;
  closedAt?: number;
  exitCode?: number;
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

export interface WorkerDetails {
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

export const WorkerToolParams = Type.Object({
  agent: Type.Optional(Type.String({ description: "Agent definition name" })),
  task: Type.Optional(Type.String({ description: "Task description" })),
  model: Type.Optional(Type.String({ description: "Override model (only honoured for agents with model: inherit)" })),
  name: Type.Optional(Type.String({ description: "Worker name suffix (auto-generated prefix)" })),
  action: Type.Optional(Type.String({ description: "'list' — list active workers" })),
});

export type WorkerToolInput = Static<typeof WorkerToolParams>;

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_WORKER_MAX_DEPTH = 2;
