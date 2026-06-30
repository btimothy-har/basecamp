import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "@sinclair/typebox";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentLaunchSpec, buildAgentTitleBase, processEnvForSpawn } from "../launch.ts";
import type { DaemonConnection } from "./client.ts";
import { createDaemonClient } from "./client.ts";
import { type ListAgentItem, type MessageStatusResultFrame, type WaitResultFrame } from "./frames.ts";

interface DispatchDetails {
	agentHandle: string;
	agent: string;
}

interface AskDetails {
	agentHandle: string;
	status: "completed" | "failed" | "running" | "unknown";
	answer?: string | null;
	error?: string | null;
	aborted?: boolean;
}

interface MessageAgentDetails {
	agentHandle: string;
	messageId: string | null;
	status: "accepted" | "unknown";
	error?: string | null;
}

interface MessageStatusDetails {
	messageId: string;
	status: MessageStatusResultFrame["status"];
	error?: string | null;
	createdAt: string | null;
	sentAt: string | null;
	queuedAt: string | null;
	failedAt: string | null;
	aborted?: boolean;
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

const AskAgentParams = Type.Object({
	agent_handle: Type.String({ description: "Target agent handle to ask" }),
	question: Type.String({ description: "Question to ask the target agent" }),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

const MessageAgentParams = Type.Object({
	agent_handle: Type.String({ description: "Target agent handle to message" }),
	message: Type.String({ description: "One-way message to persistently deliver to the target agent" }),
	interrupt: Type.Optional(
		Type.Boolean({ description: "Deliver as an interrupt/steer message instead of a follow-up" }),
	),
});

const MessageStatusParams = Type.Object({
	message_id: Type.String({ description: "Message id returned by message_agent" }),
	wait_until_delivery: Type.Optional(
		Type.Boolean({ description: "Wait until delivery reaches queued, failed, or unavailable" }),
	),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 30 })),
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

function preview(text: string | null | undefined, limit = 80): string {
	if (!text) return "";
	const compact = text.replace(/\s+/g, " ").trim();
	return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
}

function buildAskAgentTitle(agentHandle: string, question: string): string {
	return `(ask → ${agentHandle}) ${preview(question, 60)}`;
}

function requireAgentsSkillMessage(action: string): string {
	return `Load the agents skill first: call skill({ name: "agents" }) before ${action}.`;
}

function hasText(value: string | null | undefined): value is string {
	return value !== null && value !== undefined && value.trim() !== "";
}

function formatMessageStatusLine(details: MessageStatusDetails): string {
	const parts = [`message_id ${details.messageId}`, `status ${details.status}`];
	if (hasText(details.error)) parts.push(`error ${details.error}`);
	return parts.join(" • ");
}

function formatMessageStatusContent(details: MessageStatusDetails): string {
	const lines = [formatMessageStatusLine(details)];
	if (details.createdAt) lines.push(`created_at: ${details.createdAt}`);
	if (details.sentAt) lines.push(`sent_at: ${details.sentAt}`);
	if (details.queuedAt) lines.push(`queued_at: ${details.queuedAt}`);
	if (details.failedAt) lines.push(`failed_at: ${details.failedAt}`);
	return lines.join("\n");
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

export function registerPeerMessageTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<PiSwarmDependencies, "hasInvokedSkill">,
): void {
	pi.registerTool({
		name: "message_agent",
		label: "Message Agent",
		description:
			"Send a one-way persistent message to a visible async agent. Returns daemon acceptance only; no recipient response is included.",
		parameters: MessageAgentParams,
		async execute(_id, params) {
			if (!deps.hasInvokedSkill("agents")) {
				return {
					content: [{ type: "text", text: requireAgentsSkillMessage("messaging agents") }],
					isError: true,
					details: null,
				};
			}
			const targetHandle = params.agent_handle.trim();
			if (!targetHandle) {
				return {
					content: [{ type: "text", text: "message_agent requires a non-empty agent_handle." }],
					isError: true,
					details: null,
				};
			}
			const message = params.message;
			if (!message.trim()) {
				return {
					content: [{ type: "text", text: "message_agent requires a non-empty message." }],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp swarm daemon is not connected; cannot message async agents." }],
					isError: true,
					details: null,
				};
			}

			const daemonClient = createDaemonClient(connection);
			const ack = await daemonClient.sendPeerMessage({
				targetHandle,
				message,
				interrupt: Boolean(params.interrupt),
			});
			const details: MessageAgentDetails = {
				agentHandle: targetHandle,
				messageId: ack.message_id,
				status: ack.status,
				error: ack.error,
			};
			if (ack.status === "unknown") {
				const text = hasText(ack.error) ? ack.error : `No agent "${targetHandle}" is available to message.`;
				return { content: [{ type: "text", text }], isError: true, details };
			}
			return {
				content: [
					{
						type: "text",
						text: `message accepted • message_id ${ack.message_id ?? "unknown"} • status ${ack.status}`,
					},
				],
				details,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as MessageAgentDetails | null;
			const message = result.content[0]?.type === "text" ? result.content[0].text : "";
			if (!details) return new Text(message, 0, 0);
			if (details.status === "unknown") return new Text(theme.fg("warning", message || "message target unknown"), 0, 0);
			return new Text(
				theme.fg(
					"accent",
					`message accepted • message_id ${details.messageId ?? "unknown"} • status ${details.status}`,
				),
				0,
				0,
			);
		},
	});

	pi.registerTool({
		name: "message_status",
		label: "Message Status",
		description:
			"Check delivery lifecycle status for a message_agent message. Optionally waits for delivery terminal state; no answer fields are returned.",
		parameters: MessageStatusParams,
		async execute(_id, params, signal) {
			if (!deps.hasInvokedSkill("agents")) {
				return {
					content: [{ type: "text", text: requireAgentsSkillMessage("checking message status") }],
					isError: true,
					details: null,
				};
			}
			const messageId = params.message_id.trim();
			if (!messageId) {
				return {
					content: [{ type: "text", text: "message_status requires a non-empty message_id." }],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp swarm daemon is not connected; cannot check message status." }],
					isError: true,
					details: null,
				};
			}

			const daemonClient = createDaemonClient(connection);
			try {
				const status = await daemonClient.messageStatus({
					messageId,
					waitUntilDelivery: Boolean(params.wait_until_delivery),
					timeoutS: params.timeout_s === undefined ? undefined : Math.max(1, Math.floor(params.timeout_s)),
					signal,
				});
				const details: MessageStatusDetails = {
					messageId: status.message_id,
					status: status.status,
					error: status.error,
					createdAt: status.created_at,
					sentAt: status.sent_at,
					queuedAt: status.queued_at,
					failedAt: status.failed_at,
				};
				return { content: [{ type: "text", text: formatMessageStatusContent(details) }], details };
			} catch (error) {
				if (signal?.aborted || (error instanceof Error && error.message === "aborted")) {
					const details: MessageStatusDetails = {
						messageId,
						status: "unknown",
						createdAt: null,
						sentAt: null,
						queuedAt: null,
						failedAt: null,
						aborted: true,
					};
					return { content: [{ type: "text", text: "message status wait aborted" }], details };
				}
				throw error;
			}
		},
		renderResult(result, _opts, theme) {
			const details = result.details as MessageStatusDetails | null;
			if (!details) return new Text(result.content[0]?.type === "text" ? result.content[0].text : "", 0, 0);
			if (details.aborted) return new Text(theme.fg("warning", "message status wait aborted"), 0, 0);
			const color = details.status === "failed" ? "error" : details.status === "unknown" ? "warning" : "accent";
			return new Text(theme.fg(color, formatMessageStatusLine(details)), 0, 0);
		},
	});
}

export function registerAskAgentTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<
		PiSwarmDependencies,
		"hasInvokedSkill" | "getWorkspaceState" | "basecampExtensionRoot" | "resolveModelAlias"
	>,
): void {
	pi.registerTool({
		name: "ask_agent",
		label: "Ask Agent",
		description: "Ask a visible async agent a question and return its answer.",
		parameters: AskAgentParams,
		async execute(_id, params, signal, _onUpdate, ctx) {
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
			const targetHandle = params.agent_handle.trim();
			if (!targetHandle) {
				return {
					content: [{ type: "text", text: "ask_agent requires a non-empty agent_handle." }],
					isError: true,
					details: null,
				};
			}
			const agentId = randomUUID();
			const namePrefix = `ask-${randomUUID().slice(0, 6)}`;
			let agentLaunch: ReturnType<typeof buildAgentLaunchSpec>;
			try {
				agentLaunch = buildAgentLaunchSpec({
					pi,
					getAgents: discoverAgents,
					basecampExtensionRoot: deps.basecampExtensionRoot,
					requestedAgent: undefined,
					namePrefix,
					task: params.question,
					modelContext: ctx.model,
					resolveModelAlias: deps.resolveModelAlias,
					workspace: deps.getWorkspaceState(),
					agentId,
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

			let agentHandle = buildAgentHandle();
			let result: Awaited<ReturnType<typeof daemonClient.dispatchAgent>> | null = null;
			const dispatchEnv = {
				...processEnvForSpawn(),
				...plan.environment,
				BASECAMP_AGENT_TITLE: buildAskAgentTitle(targetHandle, params.question),
			};

			for (let attempt = 0; attempt < 3; attempt++) {
				result = await daemonClient.dispatchAgent({
					agentId,
					agentHandle,
					agentType: "ask",
					runKind: plan.runKind,
					model: plan.model ?? "default",
					argv: plan.args.slice(0, -1),
					task: taskSpec,
					cwd: plan.spawnCwd,
					env: dispatchEnv,
					forkFrom: targetHandle,
				});
				if (result.status !== "rejected" || result.reason !== "duplicate_agent_handle" || attempt === 2) break;
				agentHandle = buildAgentHandle();
			}

			if (!result || result.status === "rejected") {
				const message =
					result?.reason === "fork_target_unknown"
						? `No agent "${targetHandle}" is available to ask.`
						: `ask rejected: ${result?.reason ?? "unknown"}`;
				return {
					content: [{ type: "text", text: message }],
					isError: true,
					details: { agentHandle, status: "unknown", error: message } satisfies AskDetails,
				};
			}

			const timeoutS = Math.max(1, Math.floor(params.timeout_s ?? 600));
			let waitResults: WaitResultFrame["results"];
			try {
				waitResults = await daemonClient.waitForAgents({
					agentHandles: [agentHandle],
					timeoutS,
					signal,
				});
			} catch (error) {
				if (signal?.aborted || (error instanceof Error && error.message === "aborted")) {
					const details: AskDetails = { agentHandle, status: "running", aborted: true };
					return { content: [{ type: "text", text: "ask aborted" }], details };
				}
				throw error;
			}

			const answer = waitResults[0];
			if (answer?.status === "completed") {
				const details: AskDetails = { agentHandle, status: "completed", answer: answer.result };
				return { content: [{ type: "text", text: answer.result ?? "" }], details };
			}
			if (answer?.status === "failed") {
				const message = hasText(answer.error) ? answer.error : "ask failed";
				const details: AskDetails = { agentHandle, status: "failed", answer: answer.result, error: answer.error };
				return { content: [{ type: "text", text: message }], isError: true, details };
			}
			if (answer?.status === "running") {
				const message = "timed out waiting for answer";
				const details: AskDetails = { agentHandle, status: "running", error: message };
				return { content: [{ type: "text", text: message }], details };
			}

			const details: AskDetails = { agentHandle, status: "unknown" };
			return { content: [{ type: "text", text: "No answer available." }], details };
		},
		renderResult(result, _opts, theme) {
			const details = result.details as AskDetails | null;
			const message = result.content[0]?.type === "text" ? result.content[0].text : "";
			if (!details) return new Text(message, 0, 0);
			if (details.aborted) return new Text(theme.fg("warning", "ask aborted"), 0, 0);
			if (details.status === "completed") return new Text(preview(details.answer) || "(no output)", 0, 0);
			if (details.status === "failed") return new Text(theme.fg("error", preview(details.error) || "ask failed"), 0, 0);
			if (details.status === "running") {
				return new Text(theme.fg("warning", "timed out waiting for answer"), 0, 0);
			}
			return new Text(theme.fg("muted", message || "No answer available."), 0, 0);
		},
	});
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

	registerAskAgentTool(pi, getConnection, deps);
	registerPeerMessageTools(pi, getConnection, deps);

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
