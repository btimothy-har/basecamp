/**
 * Type definitions for the agent system.
 */

import * as os from "node:os";
import * as path from "node:path";
import { type Static, Type } from "@sinclair/typebox";
import type { TaskProgressSnapshot } from "../tasks/render";

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
	async: Type.Optional(Type.Boolean({ description: "Run in background, return handle immediately (read-only agents only)" })),
});

export type AgentToolInput = Static<typeof AgentToolParams>;

// ============================================================================
// Constants
// ============================================================================

export const DEFAULT_AGENT_MAX_DEPTH = 2;

const TEMP_SCOPE = `basecamp-agents-uid-${process.getuid?.() ?? "shared"}`;
export const ASYNC_BASE_DIR = path.join(os.tmpdir(), TEMP_SCOPE, "async-runs");
export const ASYNC_RESULTS_DIR = path.join(os.tmpdir(), TEMP_SCOPE, "async-results");

// ============================================================================
// Async Agent Types
// ============================================================================

/** Written by the runner script periodically to asyncDir/status.json. */
export interface AsyncStatus {
	runId: string;
	agent: string;
	task: string;
	state: "running" | "complete" | "failed";
	startedAt: number;
	lastUpdate: number;
	endedAt?: number;
	pid?: number;
	cwd: string;
	model?: string;
	toolCount: number;
	turnCount: number;
	usage: UsageStats;
	error?: string;
	taskProgress?: TaskProgressSnapshot;
}

/** Written by the runner script to ASYNC_RESULTS_DIR/{id}.json on completion. */
export interface AsyncResult {
	runId: string;
	agent: string;
	agentSource: "builtin" | "user";
	task: string;
	success: boolean;
	output: string;
	error?: string;
	model?: string;
	usage: UsageStats;
	durationMs: number;
	taskProgress?: TaskProgressSnapshot;
	sessionId?: string;
	cwd: string;
}

/** In-memory state tracked by the parent for each async job. */
export interface AsyncJobState {
	asyncId: string;
	asyncDir: string;
	agent: string;
	agentSource: "builtin" | "user";
	task: string;
	status: "queued" | "running" | "complete" | "failed";
	startedAt: number;
	updatedAt: number;
	model?: string;
	toolCount?: number;
	turnCount?: number;
	taskProgress?: TaskProgressSnapshot;
}

/** Config file written to asyncDir for the runner script to read. */
export interface AsyncRunnerConfig {
	runId: string;
	agent: string;
	agentSource: "builtin" | "user";
	task: string;
	cwd: string;
	model: string | undefined;
	piArgs: string[];
	asyncDir: string;
	resultsDir: string;
	sessionId?: string;
}

export const AGENT_ASYNC_STARTED_EVENT = "agent:async-started";
export const AGENT_ASYNC_COMPLETE_EVENT = "agent:async-complete";

// ============================================================================
// Async Dispatch Validation
// ============================================================================

const WRITE_TOOLS = new Set(["write", "edit"]);

export function canDispatchAsync(
	agentConfig: import("./discovery.ts").AgentConfig | null,
): { ok: boolean; reason?: string } {
	if (!agentConfig) {
		return { ok: false, reason: "Ad-hoc agents cannot be dispatched asynchronously" };
	}
	if (!agentConfig.tools?.length) {
		return {
			ok: false,
			reason: `Agent "${agentConfig.name}" has no tool restrictions — async requires a read-only toolset`,
		};
	}
	const writeTools = agentConfig.tools.filter((t) => WRITE_TOOLS.has(t));
	if (writeTools.length > 0) {
		return {
			ok: false,
			reason: `Agent "${agentConfig.name}" has write tools (${writeTools.join(", ")}) — async requires a read-only toolset`,
		};
	}
	return { ok: true };
}
