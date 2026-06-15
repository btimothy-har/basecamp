import { randomUUID } from "node:crypto";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "@sinclair/typebox";
import { hasInvokedSkill } from "../../../platform/skill-tracker.ts";
import { getWorkspaceState } from "../../../platform/workspace.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentRunName, buildPiArgs, sanitizeAgentSpawnEnv } from "../executor.ts";
import { resolveModel } from "../model-resolution.ts";
import { buildAgentEnv, getBasecampExtensionToolNames } from "../tool.ts";
import { getAgentRunKind } from "../types.ts";
import type { DaemonConnection } from "./client.ts";
import {
	type DispatchAckFrame,
	type ListAgentItem,
	type ListAgentsResultFrame,
	PROTOCOL_VERSION,
	type WaitResultFrame,
} from "./frames.ts";
import { resolveDaemonPaths } from "./paths.ts";

interface DispatchDetails {
	agentId: string;
	agent: string;
}

interface ListAgentsDetails {
	agents: ListAgentItem[];
}

interface WaitHandleResult {
	agentId: string;
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
		Type.String({ description: "Agent handle returned by dispatch_agent" }),
		Type.Array(Type.String({ description: "Agent handle returned by dispatch_agent" })),
	]),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

const ListAgentsParams = Type.Object({
	awaitable: Type.Optional(
		Type.Boolean({
			description: "Filter to agents currently awaitable by this caller",
		}),
	),
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

function sameAsRequested(resultAgentIds: string[], requestedSet: Set<string>): boolean {
	const resultSet = new Set(resultAgentIds);
	if (resultSet.size !== requestedSet.size) return false;
	return [...requestedSet].every((agentId) => resultSet.has(agentId));
}

function hasText(value: string | null): value is string {
	return value !== null && value.trim() !== "";
}

function formatWaitItemText(item: WaitHandleResult): string {
	if (item.status === "completed") {
		return `✓ ${item.agentId} completed\n${hasText(item.result) ? item.result : "(no output)"}`;
	}
	if (item.status === "failed") {
		const parts = [`✗ ${item.agentId} failed`, `error:\n${hasText(item.error) ? item.error : "unknown error"}`];
		if (hasText(item.result)) parts.push(`result:\n${item.result}`);
		return parts.join("\n");
	}
	if (item.status === "unknown") return `? ${item.agentId} unknown agent`;
	return `… ${item.agentId} still running (timed out)`;
}

function buildListAgentLine(agent: ListAgentItem): string {
	const awaitableText = agent.awaitable ? "awaitable" : "not awaitable";
	const parent = agent.parent_id ? `parent ${agent.parent_id}` : "root";
	return `${agent.agent_id} — ${agent.session_name}\n${agent.status} • ${awaitableText} • ${parent} • depth ${agent.depth}`;
}

function shortListAgentsSummary(agents: ListAgentItem[]): string {
	if (agents.length === 0) return "No agents found in this scope.";
	return agents.map((agent) => buildListAgentLine(agent)).join("\n\n");
}

function waitForFrame<T extends "dispatch_ack" | "wait_result" | "list_agents_result">(
	connection: DaemonConnection,
	type: T,
	predicate: (frame: Extract<DispatchAckFrame | WaitResultFrame | ListAgentsResultFrame, { type: T }>) => boolean,
	signal?: AbortSignal,
): Promise<Extract<DispatchAckFrame | WaitResultFrame | ListAgentsResultFrame, { type: T }>> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) {
			reject(new Error("aborted"));
			return;
		}

		const off = connection.on(type, (frame) => {
			const typed = frame as Extract<DispatchAckFrame | WaitResultFrame | ListAgentsResultFrame, { type: T }>;
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
		description: "Dispatch an agent asynchronously and return an agent handle.",
		parameters: DispatchAgentParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (!hasInvokedSkill("agents")) {
				return {
					content: [
						{ type: "text", text: 'Load the agents skill first: call skill({ name: "agents" }) before dispatching.' },
					],
					isError: true,
					details: null,
				};
			}
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
					details: { agentId, agent: params.agent ?? "ad-hoc" } satisfies DispatchDetails,
				};
			}

			return {
				content: [{ type: "text", text: `⏳ dispatched ${params.agent ?? "ad-hoc"} — handle ${agentId}` }],
				details: { agentId, agent: params.agent ?? "ad-hoc" } satisfies DispatchDetails,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as DispatchDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			return new Text(theme.fg("accent", `⏳ dispatched ${details.agent} — handle ${details.agentId}`), 0, 0);
		},
	});

	pi.registerTool({
		name: "list_agents",
		label: "List Agents",
		description: "List visible async agents under the caller's daemon root.",
		parameters: ListAgentsParams,
		async execute(_id, params, _signal) {
			if (!hasInvokedSkill("agents")) {
				return {
					content: [
						{
							type: "text",
							text: 'Load the agents skill first: call skill({ name: "agents" }) before listing agents.',
						},
					],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp daemon is not connected; cannot list async agents." }],
					isError: true,
					details: null,
				};
			}

			const requestId = randomUUID();
			connection.send({
				type: "list_agents",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				awaitable: Boolean(params.awaitable),
			});

			const frame = await waitForFrame(
				connection,
				"list_agents_result",
				(candidate) => candidate.request_id === requestId,
			);

			return {
				content: [{ type: "text", text: shortListAgentsSummary(frame.agents) }],
				details: { agents: frame.agents } as ListAgentsDetails,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as ListAgentsDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			if (details.agents.length === 0) return new Text(theme.fg("muted", "No agents visible."), 0, 0);
			const lines = details.agents.map((agent) => {
				const status = `${theme.fg(agent.status === "running" || agent.status === "failed" ? "warning" : "muted", agent.status)}`;
				const awaitable = theme.fg(
					agent.awaitable ? "success" : "muted",
					agent.awaitable ? "awaitable" : "not awaitable",
				);
				return `${agent.agent_id} ${theme.fg("muted", agent.session_name)} ${status} ${awaitable}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});

	pi.registerTool({
		name: "wait_for_agent",
		label: "Wait For Agent",
		description: "Wait for one or more async agent handles to complete.",
		parameters: WaitForAgentParams,
		async execute(_id, params, signal) {
			if (!hasInvokedSkill("agents")) {
				return {
					content: [
						{ type: "text", text: 'Load the agents skill first: call skill({ name: "agents" }) before dispatching.' },
					],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp daemon is not connected; cannot wait for async agent handles." }],
					isError: true,
					details: null,
				};
			}

			const agentIds = normalizeHandles(params.handles);
			if (agentIds.length === 0) {
				return { content: [{ type: "text", text: "No handles provided." }], isError: true, details: null };
			}

			const timeoutS = Math.max(1, Math.floor(params.timeout_s ?? 600));
			const requested = new Set(agentIds);
			connection.send({
				type: "wait",
				v: PROTOCOL_VERSION,
				agent_ids: agentIds,
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
							candidate.results.map((item) => item.agent_id),
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

			const byId = new Map(frame.results.map((item) => [item.agent_id, item]));
			const items: WaitHandleResult[] = agentIds.map((agentId) => {
				const hit = byId.get(agentId);
				if (!hit) {
					return {
						agentId,
						status: "unknown",
						result: null,
						error: null,
					};
				}
				if (hit.status === "failed") {
					return {
						agentId,
						status: "failed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "completed") {
					return {
						agentId,
						status: "completed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "running") {
					return {
						agentId,
						status: "running",
						result: null,
						error: "still running (timed out)",
					};
				}
				return {
					agentId,
					status: "unknown",
					result: null,
					error: null,
				};
			});

			const lines = items.map(formatWaitItemText);
			const details: WaitDetails = { items };
			return { content: [{ type: "text", text: lines.join("\n\n") }], details };
		},
		renderResult(result, _opts, theme) {
			const details = result.details as WaitDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			if (details.aborted) return new Text(theme.fg("warning", "wait aborted"), 0, 0);
			const lines = details.items.map((item) => {
				if (item.status === "completed") {
					return `${theme.fg("success", "✓")} ${item.agentId} ${theme.fg("muted", preview(item.result) || "completed")}`;
				}
				if (item.status === "failed") {
					return `${theme.fg("error", "✗")} ${item.agentId} ${theme.fg("error", preview(item.error) || "failed")}`;
				}
				if (item.status === "unknown") {
					return `${theme.fg("warning", "?")} ${item.agentId} ${theme.fg("muted", "unknown agent")}`;
				}
				return `${theme.fg("warning", "…")} ${item.agentId} ${theme.fg("muted", "still running (timed out)")}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
