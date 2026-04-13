/**
 * Type definitions for the agent/worker system.
 */

import { Type, type Static } from "@sinclair/typebox";

// ============================================================================
// Agent Definitions
// ============================================================================

export interface AgentConfig {
  name: string;
  description: string;
  model?: string;
  thinking?: string;
  tools?: string[];
  extensions?: string[];
  skills?: string[];
  mode: "pane" | "background";
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
  mode: "pane" | "background";
  status: "running" | "closed";
  pid?: number;
  sessionDir?: string;
  model: string;
  task: string;
  createdAt: number;
  closedAt?: number;
}

// ============================================================================
// Tool Schema
// ============================================================================

export const WorkerToolParams = Type.Object({
  agent: Type.Optional(Type.String({ description: "Agent definition name" })),
  task: Type.Optional(Type.String({ description: "Task description" })),
  mode: Type.Optional(
    Type.String({ description: "'pane' (visible Kitty window) or 'background' (headless)" }),
  ),
  model: Type.Optional(Type.String({ description: "Override model" })),
  name: Type.Optional(Type.String({ description: "Worker name suffix (auto-generated prefix)" })),
  action: Type.Optional(Type.String({ description: "'list' — list active workers" })),
});

export type WorkerToolInput = Static<typeof WorkerToolParams>;

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_WORKER_MAX_DEPTH = 2;
