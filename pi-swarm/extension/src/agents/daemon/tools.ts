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
	agentHandle: string;
	agent: string;
}

interface PublicListAgentItem {
	agentHandle: string;
	role: string;
	sessionName: string;
	depth: number;
	status: "pending" | "running" | "completed" | "failed" | "idle";
	awaitable: boolean;
}

interface ListAgentsDetails {
	agents: PublicListAgentItem[];
}

interface WaitHandleResult {
	agentHandle: string;
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
	agent_handle: Type.Optional(Type.String({ description: "Existing agent handle to retask" })),
});

const AgentHandlesParam = Type.Union([
	Type.String({ description: "Agent handle returned by dispatch_agent" }),
	Type.Array(Type.String({ description: "Agent handle returned by dispatch_agent" })),
]);

const WaitForAgentParams = Type.Object({
	agent_handles: Type.Optional(AgentHandlesParam),
	handles: Type.Optional(AgentHandlesParam),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

const ListAgentsParams = Type.Object({
	awaitable: Type.Optional(
		Type.Boolean({
			description: "Filter to agents currently awaitable by this caller",
		}),
	),
});

const HANDLE_ADJECTIVES = [
	"amber",
	"brisk",
	"calm",
	"clear",
	"ember",
	"mossy",
	"quiet",
	"silver",
	"steady",
	"swift",
] as const;
const HANDLE_NOUNS = ["badger", "falcon", "fox", "heron", "lynx", "otter", "panda", "raven", "tiger", "wren"] as const;

function buildAgentHandle(): string {
	const entropy = randomUUID().replace(/-/g, "");
	const adjective = HANDLE_ADJECTIVES[Number.parseInt(entropy.slice(0, 2), 16) % HANDLE_ADJECTIVES.length];
	const noun = HANDLE_NOUNS[Number.parseInt(entropy.slice(2, 4), 16) % HANDLE_NOUNS.length];
	return `${adjective}-${noun}-${entropy.slice(4, 10)}`;
}

function normalizeHandles(input: string | string[] | undefined): string[] {
	if (input === undefined) return [];
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
		return `✓ ${item.agentHandle} completed\n${hasText(item.result) ? item.result : "(no output)"}`;
	}
	if (item.status === "failed") {
		const parts = [`✗ ${item.agentHandle} failed`, `error:\n${hasText(item.error) ? item.error : "unknown error"}`];
		if (hasText(item.result)) parts.push(`result:\n${item.result}`);
		return parts.join("\n");
	}
	if (item.status === "unknown") return `? ${item.agentHandle} unknown agent`;
	return `… ${item.agentHandle} still running (timed out)`;
}

function publicAgentHandle(agent: ListAgentItem): string {
	return agent.agent_handle?.trim() || agent.agent_id;
}

function storedAgentType(agent: ListAgentItem): string | null {
	const value = agent.agent_type?.trim();
	return value ? value : null;
}

function toPublicListAgent(agent: ListAgentItem): PublicListAgentItem {
	return {
		agentHandle: publicAgentHandle(agent),
		role: agent.role,
		sessionName: agent.session_name,
		depth: agent.depth,
		status: agent.status,
		awaitable: agent.awaitable,
	};
}

function buildListAgentLine(agent: PublicListAgentItem): string {
	const awaitableText = agent.awaitable ? "awaitable" : "not awaitable";
	return `${agent.agentHandle} — ${agent.sessionName}\n${agent.status} • ${awaitableText} • ${agent.role} • depth ${agent.depth}`;
}

function shortListAgentsSummary(agents: PublicListAgentItem[]): string {
	if (agents.length === 0) return "No agents found in this scope.";
	return agents.map((agent) => buildListAgentLine(agent)).join("\n\n");
}

export function registerDaemonTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<
		PiSwarmDependencies,
		"hasInvokedSkill" | "getWorkspaceState" | "basecampExtensionRoot" | "resolveModelAlias"
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
						{
							type: "text",
							text: 'Load the agents skill first: call skill({ name: "agents" }) before dispatching.',
						},
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
							text: "basecamp swarm daemon is not connected; dispatch cannot proceed.",
						},
					],
					isError: true,
					details: null,
				};
			}

			const daemonClient = createDaemonClient(connection);
			const requestedHandle = params.agent_handle?.trim() || null;
			let requestedAgent = params.agent;
			let agentId: string = randomUUID();
			if (requestedHandle) {
				const existing = (await daemonClient.listAgents({ awaitable: false })).find(
					(agent) => publicAgentHandle(agent) === requestedHandle,
				);
				if (!existing) {
					return {
						content: [{ type: "text", text: `Unknown agent handle: ${requestedHandle}` }],
						isError: true,
						details: null,
					};
				}

				const existingAgentType = storedAgentType(existing);
				if (params.agent && existingAgentType && params.agent !== existingAgentType) {
					return {
						content: [
							{
								type: "text",
								text: `Agent handle ${requestedHandle} is ${existingAgentType}; use a new handle for ${params.agent}.`,
							},
						],
						isError: true,
						details: { agentHandle: requestedHandle, agent: existingAgentType } satisfies DispatchDetails,
					};
				}
				if (!requestedAgent && existingAgentType && existingAgentType !== "ad-hoc") requestedAgent = existingAgentType;
				agentId = existing.agent_id;
			}

			const localId = randomUUID().slice(0, 6);
			const namePrefix = `agent-${localId}`;
			let agentLaunch: ReturnType<typeof buildAgentLaunchSpec>;
			try {
				agentLaunch = buildAgentLaunchSpec({
					pi,
					getAgents: discoverAgents,
					basecampExtensionRoot: deps.basecampExtensionRoot,
					agentId,
					requestedAgent,
					namePrefix,
					nameSuffix: params.name,
					task: params.task,
					modelContext: ctx.model,
					resolveModelAlias: deps.resolveModelAlias,
					workspace: deps.getWorkspaceState(),
					parentSession:
						process.env.BASECAMP_SESSION_NAME ?? pi.getSessionName()?.trim() ?? ctx.sessionManager.getSessionId(),
					project: process.env.BASECAMP_PROJECT ?? "default",
				});
			} catch (error) {
				const msg = error instanceof Error ? error.message : String(error);
				return { content: [{ type: "text", text: msg }], isError: true, details: null };
			}
			if (!agentLaunch.ok) {
				const msg = agentLaunch.message;
				return { content: [{ type: "text", text: msg }], isError: true, details: null };
			}

			const { plan } = agentLaunch;
			const taskSpec = plan.args.at(-1);
			if (!taskSpec) {
				return {
					content: [{ type: "text", text: "Unable to build async task argument." }],
					isError: true,
					details: null,
				};
			}

			let agentHandle = requestedHandle ?? buildAgentHandle();
			let result: Awaited<ReturnType<typeof daemonClient.dispatchAgent>> | null = null;
			const dispatchEnv = {
				...processEnvForSpawn(),
				...plan.environment,
				BASECAMP_AGENT_TITLE: buildAgentTitleBase(requestedAgent, params.task),
			};

			const attempts = requestedHandle ? 1 : 3;
			for (let attempt = 0; attempt < attempts; attempt++) {
				result = await daemonClient.dispatchAgent({
					agentId,
					agentHandle,
					agentType: plan.agentLabel ?? "ad-hoc",
					runKind: plan.runKind,
					model: plan.model ?? "default",
					argv: plan.args.slice(0, -1),
					task: taskSpec,
					cwd: plan.spawnCwd,
					env: dispatchEnv,
				});
				if (result.status !== "rejected" || result.reason !== "duplicate_agent_handle" || attempt === attempts - 1)
					break;
				agentHandle = buildAgentHandle();
			}

			if (!result || result.status === "rejected") {
				return {
					content: [{ type: "text", text: `dispatch rejected: ${result?.reason ?? "unknown"}` }],
					isError: true,
					details: { agentHandle, agent: plan.agentLabel ?? "ad-hoc" } satisfies DispatchDetails,
				};
			}

			return {
				content: [{ type: "text", text: `⏳ dispatched ${plan.agentLabel ?? "ad-hoc"} — handle ${agentHandle}` }],
				details: { agentHandle, agent: plan.agentLabel ?? "ad-hoc" } satisfies DispatchDetails,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as DispatchDetails | null;
			const message = result.content[0]?.type === "text" ? result.content[0].text : "";
			const isError = (result as { isError?: boolean }).isError === true;
			if (!details || isError) return new Text(message, 0, 0);
			return new Text(theme.fg("accent", `⏳ dispatched ${details.agent} — handle ${details.agentHandle}`), 0, 0);
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
					content: [{ type: "text", text: "basecamp swarm daemon is not connected; cannot list async agents." }],
					isError: true,
					details: null,
				};
			}

			const daemonClient = createDaemonClient(connection);
			const agents = (await daemonClient.listAgents({ awaitable: Boolean(params.awaitable) })).map(toPublicListAgent);

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
				return `${agent.agentHandle} ${theme.fg("muted", agent.sessionName)} ${status} ${awaitable}`;
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
						{
							type: "text",
							text: 'Load the agents skill first: call skill({ name: "agents" }) before dispatching.',
						},
					],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [
						{ type: "text", text: "basecamp swarm daemon is not connected; cannot wait for async agent handles." },
					],
					isError: true,
					details: null,
				};
			}

			const agentHandles = normalizeHandles(params.agent_handles ?? params.handles);
			if (agentHandles.length === 0) {
				return { content: [{ type: "text", text: "No agent handles provided." }], isError: true, details: null };
			}

			const timeoutS = Math.max(1, Math.floor(params.timeout_s ?? 600));
			const daemonClient = createDaemonClient(connection);
			let results: WaitResultFrame["results"];
			try {
				results = await daemonClient.waitForAgents({
					agentHandles,
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

			const byHandle = new Map(results.map((item) => [item.agent_handle, item]));
			const items: WaitHandleResult[] = agentHandles.map((agentHandle) => {
				const hit = byHandle.get(agentHandle);
				if (!hit) {
					return {
						agentHandle,
						status: "unknown",
						result: null,
						error: null,
					};
				}
				if (hit.status === "failed") {
					return {
						agentHandle,
						status: "failed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "completed") {
					return {
						agentHandle,
						status: "completed",
						result: hit.result,
						error: hit.error,
					};
				}
				if (hit.status === "running") {
					return {
						agentHandle,
						status: "running",
						result: null,
						error: "still running (timed out)",
					};
				}
				return {
					agentHandle,
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
					return `${theme.fg("success", "✓")} ${item.agentHandle} ${theme.fg("muted", preview(item.result) || "completed")}`;
				}
				if (item.status === "failed") {
					return `${theme.fg("error", "✗")} ${item.agentHandle} ${theme.fg("error", preview(item.error) || "failed")}`;
				}
				if (item.status === "unknown") {
					return `${theme.fg("warning", "?")} ${item.agentHandle} ${theme.fg("muted", "unknown agent")}`;
				}
				return `${theme.fg("warning", "…")} ${item.agentHandle} ${theme.fg("muted", "still running (timed out)")}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
