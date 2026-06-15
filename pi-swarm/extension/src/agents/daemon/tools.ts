import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "@sinclair/typebox";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentLaunchSpec, buildAgentTitleBase, processEnvForSpawn } from "../launch.ts";
import type { DaemonConnection } from "./client.ts";
import { createDaemonClient } from "./client.ts";
import { type ListAgentItem, type WaitResultFrame } from "./frames.ts";

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

function normalizeHandles(input: string | string[]): string[] {
	const values = Array.isArray(input) ? input : [input];
	return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function preview(text: string | null, limit = 80): string {
	if (!text) return "";
	const compact = text.replace(/\s+/g, " ").trim();
	return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
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

export function registerDaemonTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<
		PiSwarmDependencies,
		| "hasInvokedSkill"
		| "getWorkspaceState"
		| "basecampExtensionRoot"
		| "resolveModelAlias"
		| "readSkillContent"
		| "buildSkillBlock"
	>,
): void {
	pi.registerTool({
		name: "dispatch_agent",
		label: "Dispatch Agent",
		description: "Dispatch an agent asynchronously and return an agent handle.",
		parameters: DispatchAgentParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (!deps.hasInvokedSkill("agents")) {
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

			const localId = randomUUID().slice(0, 6);
			const agentId = randomUUID();
			const namePrefix = `agent-${localId}`;
			let agentLaunch: ReturnType<typeof buildAgentLaunchSpec>;
			try {
				agentLaunch = buildAgentLaunchSpec({
					pi,
					getAgents: discoverAgents,
					basecampExtensionRoot: deps.basecampExtensionRoot,
					agentId,
					requestedAgent: params.agent,
					namePrefix,
					nameSuffix: params.name,
					task: params.task,
					modelContext: ctx.model,
					resolveModelAlias: deps.resolveModelAlias,
					workspace: deps.getWorkspaceState(),
					mode: "daemon",
					parentSession:
						process.env.BASECAMP_SESSION_NAME ?? pi.getSessionName()?.trim() ?? ctx.sessionManager.getSessionId(),
					project: process.env.BASECAMP_PROJECT ?? "default",
					piArgsDeps: {
						readSkillContent: deps.readSkillContent,
						buildSkillBlock: deps.buildSkillBlock,
					},
				});
			} catch (error) {
				const msg = error instanceof Error ? error.message : String(error);
				return { content: [{ type: "text", text: msg }], isError: true, details: null };
			}
			if (!agentLaunch.ok) {
				const msg = agentLaunch.message;
				return { content: [{ type: "text", text: msg }], isError: true, details: null };
			}

			const daemonClient = createDaemonClient(connection);
			const { plan } = agentLaunch;
			const result = await daemonClient.dispatchAgent({
				agentId,
				argv: plan.args.slice(0, -1),
				task: `Task: ${params.task}`,
				cwd: plan.spawnCwd,
				env: {
					...processEnvForSpawn(),
					...plan.environment,
					BASECAMP_AGENT_TITLE: buildAgentTitleBase(params.agent, params.task),
				},
			});
			if (result.status === "rejected") {
				return {
					content: [{ type: "text", text: `dispatch rejected: ${result.reason ?? "unknown"}` }],
					isError: true,
					details: { agentId, agent: plan.agentLabel ?? "ad-hoc" } satisfies DispatchDetails,
				};
			}

			return {
				content: [{ type: "text", text: `⏳ dispatched ${plan.agentLabel ?? "ad-hoc"} — handle ${agentId}` }],
				details: { agentId, agent: plan.agentLabel ?? "ad-hoc" } satisfies DispatchDetails,
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
			if (!deps.hasInvokedSkill("agents")) {
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

			const daemonClient = createDaemonClient(connection);
			const agents = await daemonClient.listAgents({ awaitable: Boolean(params.awaitable) });

			return {
				content: [{ type: "text", text: shortListAgentsSummary(agents) }],
				details: { agents } as ListAgentsDetails,
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
			if (!deps.hasInvokedSkill("agents")) {
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
			const daemonClient = createDaemonClient(connection);
			let results: WaitResultFrame["results"];
			try {
				results = await daemonClient.waitForAgents({
					agentIds,
					timeoutS,
					signal,
				});
			} catch (error) {
				if (signal?.aborted || (error instanceof Error && error.message === "aborted")) {
					const details: WaitDetails = { items: [], aborted: true };
					return { content: [{ type: "text", text: "wait aborted" }], details };
				}
				throw error;
			}

			const byId = new Map(results.map((item) => [item.agent_id, item]));
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
