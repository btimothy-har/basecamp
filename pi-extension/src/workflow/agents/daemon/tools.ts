import { randomUUID } from "node:crypto";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "@sinclair/typebox";
import { getWorkspaceState } from "../../../platform/workspace.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentRunName, buildPiArgs, sanitizeAgentSpawnEnv } from "../executor.ts";
import { resolveModel } from "../model-resolution.ts";
import { buildAgentEnv, getBasecampExtensionToolNames } from "../tool.ts";
import { getAgentRunKind } from "../types.ts";
import type { DaemonConnection } from "./client.ts";
import { type DispatchAckFrame, PROTOCOL_VERSION, type WaitResultFrame } from "./frames.ts";
import { resolveDaemonPaths } from "./paths.ts";

interface DispatchDetails {
	runId: string;
	agent: string;
}

interface WaitHandleResult {
	runId: string;
	status: "completed" | "failed" | "running" | "unknown";
	result: string | null;
	error: string | null;
}

interface WaitDetails {
	items: WaitHandleResult[];
	aborted?: boolean;
}

const DispatchAgentParams = Type.Object({
	agent: Type.Optional(Type.String({ description: "Agent definition name" })),
	task: Type.String({ description: "Task description" }),
	name: Type.Optional(Type.String({ description: "Name suffix (auto-generated prefix)" })),
});

const WaitForAgentParams = Type.Object({
	handles: Type.Union([
		Type.String({ description: "Run handle returned by dispatch_agent" }),
		Type.Array(Type.String({ description: "Run handle returned by dispatch_agent" })),
	]),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

export function processEnvForSpawn(): Record<string, string> {
	const env: Record<string, string> = {};
	for (const [key, value] of Object.entries(process.env)) {
		if (typeof value === "string") env[key] = value;
	}
	return sanitizeAgentSpawnEnv(env);
}

function compactAgentTaskLabel(task: string, maxChars = 56): string {
	const oneLine = task.replace(/\s+/g, " ").trim();
	if (oneLine.length <= maxChars) return oneLine;
	return `${oneLine.slice(0, maxChars - 1).trimEnd()}…`;
}

export function buildAgentTitleBase(agentName: string | null | undefined, task: string): string {
	const prefix = agentName?.trim() ? agentName.trim() : "Agent";
	return `(${prefix}) ${compactAgentTaskLabel(task)}`;
}

function normalizeHandles(input: string | string[]): string[] {
	const values = Array.isArray(input) ? input : [input];
	return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function preview(text: string | null, limit = 80): string {
	if (!text) return "";
	const compact = text.replace(/\s+/g, " ").trim();
	return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
}

function sameAsRequested(resultRunIds: string[], requestedSet: Set<string>): boolean {
	if (resultRunIds.length !== requestedSet.size) return false;
	return resultRunIds.every((runId) => requestedSet.has(runId));
}

function waitForFrame<T extends "dispatch_ack" | "wait_result">(
	connection: DaemonConnection,
	type: T,
	predicate: (frame: Extract<DispatchAckFrame | WaitResultFrame, { type: T }>) => boolean,
	signal?: AbortSignal,
): Promise<Extract<DispatchAckFrame | WaitResultFrame, { type: T }>> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) {
			reject(new Error("aborted"));
			return;
		}

		const off = connection.on(type, (frame) => {
			const typed = frame as Extract<DispatchAckFrame | WaitResultFrame, { type: T }>;
			if (!predicate(typed)) return;
			off();
			signal?.removeEventListener("abort", onAbort);
			resolve(typed);
		});

		const onAbort = () => {
			off();
			reject(new Error("aborted"));
		};
		signal?.addEventListener("abort", onAbort, { once: true });
	});
}

export function registerDaemonTools(pi: ExtensionAPI, getConnection: () => Promise<DaemonConnection | null>): void {
	pi.registerTool({
		name: "dispatch_agent",
		label: "Dispatch Agent",
		description: "Dispatch an agent asynchronously and return a run handle.",
		parameters: DispatchAgentParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [
						{
							type: "text",
							text: "basecamp daemon is not connected. Use the synchronous agent tool as fallback.",
						},
					],
					isError: true,
					details: null,
				};
			}

			const agents = discoverAgents();
			const agentConfig = params.agent ? (agents.find((agent) => agent.name === params.agent) ?? null) : null;
			if (params.agent && !agentConfig) {
				const available = agents.map((agent) => agent.name).join(", ") || "none";
				return {
					content: [{ type: "text", text: `Unknown agent: ${params.agent}. Available: ${available}` }],
					isError: true,
					details: null,
				};
			}

			const model = resolveModel(agentConfig?.model ?? "inherit", ctx.model);
			const localId = randomUUID().slice(0, 6);
			const prefix = `agent-${localId}`;
			let name: string;
			try {
				name = buildAgentRunName(prefix, params.name);
			} catch (error) {
				const msg = error instanceof Error ? error.message : String(error);
				return {
					content: [{ type: "text", text: msg }],
					isError: true,
					details: null,
				};
			}
			const project = process.env.BASECAMP_PROJECT ?? "default";
			const parentSession =
				process.env.BASECAMP_SESSION_NAME ?? pi.getSessionName()?.trim() ?? ctx.sessionManager.getSessionId();
			const basecampEnv = buildAgentEnv({ name, parentSession, project });
			const extensionTools = getBasecampExtensionToolNames(pi);
			const workspace = getWorkspaceState();
			const worktreeDir = workspace?.activeWorktree?.path ?? null;
			const spawnCwd = workspace?.protectedRoot ?? workspace?.repo?.root ?? workspace?.launchCwd ?? process.cwd();

			if (getAgentRunKind(agentConfig) === "mutative" && !worktreeDir) {
				return {
					content: [
						{
							type: "text",
							text: "Mutative worker agents require an active execution worktree. Approve an implementation plan and activate a worktree first.",
						},
					],
					isError: true,
					details: null,
				};
			}

			const agentId = randomUUID();
			const sessionDir = path.join(resolveDaemonPaths().runtimeDir, "agents", agentId, "session");
			const { args } = buildPiArgs(agentConfig, params.task, {
				name,
				model,
				cwd: spawnCwd,
				worktreeDir,
				env: basecampEnv,
				sessionDir,
				sessionId: agentId,
				extensionTools,
			});

			const runId = randomUUID();
			connection.send({
				type: "dispatch",
				v: PROTOCOL_VERSION,
				run_id: runId,
				agent_id: agentId,
				spec: {
					argv: args.slice(0, -1),
					task: `Task: ${params.task}`,
					cwd: spawnCwd,
					env: {
						...processEnvForSpawn(),
						...sanitizeAgentSpawnEnv(basecampEnv),
						BASECAMP_AGENT_TITLE: buildAgentTitleBase(params.agent, params.task),
					},
					resume_path: null,
				},
			});

			const ack = await waitForFrame(connection, "dispatch_ack", (frame) => frame.run_id === runId);
			if (ack.status === "rejected") {
				return {
					content: [{ type: "text", text: `dispatch rejected: ${ack.reason ?? "unknown"}` }],
					isError: true,
					details: { runId, agent: params.agent ?? "ad-hoc" } satisfies DispatchDetails,
				};
			}

			return {
				content: [{ type: "text", text: `⏳ dispatched ${params.agent ?? "ad-hoc"} — handle ${runId}` }],
				details: { runId, agent: params.agent ?? "ad-hoc" } satisfies DispatchDetails,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as DispatchDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			return new Text(theme.fg("accent", `⏳ dispatched ${details.agent} — handle ${details.runId}`), 0, 0);
		},
	});

	pi.registerTool({
		name: "wait_for_agent",
		label: "Wait For Agent",
		description: "Wait for one or more async agent handles to complete.",
		parameters: WaitForAgentParams,
		async execute(_id, params, signal) {
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp daemon is not connected; cannot wait for async agent handles." }],
					isError: true,
					details: null,
				};
			}

			const runIds = normalizeHandles(params.handles);
			if (runIds.length === 0) {
				return { content: [{ type: "text", text: "No handles provided." }], isError: true, details: null };
			}

			const timeoutS = Math.max(1, Math.floor(params.timeout_s ?? 600));
			const requested = new Set(runIds);
			connection.send({
				type: "wait",
				v: PROTOCOL_VERSION,
				run_ids: runIds,
				mode: "all",
				timeout_s: timeoutS,
			});

			let frame: WaitResultFrame;
			try {
				frame = await waitForFrame(
					connection,
					"wait_result",
					(candidate) =>
						sameAsRequested(
							candidate.results.map((item) => item.run_id),
							requested,
						),
					signal,
				);
			} catch (error) {
				if (signal?.aborted || (error instanceof Error && error.message === "aborted")) {
					const details: WaitDetails = { items: [], aborted: true };
					return { content: [{ type: "text", text: "wait aborted" }], details };
				}
				throw error;
			}

			const byId = new Map(frame.results.map((item) => [item.run_id, item]));
			const items: WaitHandleResult[] = runIds.map((runId) => {
				const hit = byId.get(runId);
				if (!hit) {
					return {
						runId,
						status: "unknown",
						result: null,
						error: null,
					};
				}
				if (hit.status === "failed") {
					return {
						runId,
						status: "failed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "completed") {
					return {
						runId,
						status: "completed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "running") {
					return {
						runId,
						status: "running",
						result: null,
						error: "still running (timed out)",
					};
				}
				return {
					runId,
					status: "unknown",
					result: null,
					error: null,
				};
			});

			const lines = items.map((item) => {
				if (item.status === "completed") return `✓ ${item.runId} completed`;
				if (item.status === "failed") return `✗ ${item.runId} failed: ${preview(item.error) || "error"}`;
				if (item.status === "unknown") return `? ${item.runId} unknown handle`;
				return `… ${item.runId} still running (timed out)`;
			});
			const details: WaitDetails = { items };
			return { content: [{ type: "text", text: lines.join("\n") }], details };
		},
		renderResult(result, _opts, theme) {
			const details = result.details as WaitDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			if (details.aborted) return new Text(theme.fg("warning", "wait aborted"), 0, 0);
			const lines = details.items.map((item) => {
				if (item.status === "completed") {
					return `${theme.fg("success", "✓")} ${item.runId} ${theme.fg("muted", preview(item.result) || "completed")}`;
				}
				if (item.status === "failed") {
					return `${theme.fg("error", "✗")} ${item.runId} ${theme.fg("error", preview(item.error) || "failed")}`;
				}
				if (item.status === "unknown") {
					return `${theme.fg("warning", "?")} ${item.runId} ${theme.fg("muted", "unknown handle")}`;
				}
				return `${theme.fg("warning", "…")} ${item.runId} ${theme.fg("muted", "still running (timed out)")}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
