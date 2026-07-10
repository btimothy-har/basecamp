import { Type } from "@sinclair/typebox";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import type { CancelAckFrame, ListAgentItem, MessageStatusResultFrame } from "../frames/index.ts";

/** Capabilities daemon tools need from the host session (injectable for tests). */
export interface DaemonToolDeps {
	hasInvokedSkill: (name: string) => boolean;
	getWorkspaceState: () => WorkspaceState | null;
	basecampExtensionRoot: string;
	resolveModelAlias: (alias: string) => string | undefined;
}

export interface DispatchDetails {
	agentHandle: string;
	agent: string;
}

export interface AskDetails {
	agentHandle: string;
	status: "completed" | "failed" | "running" | "unknown";
	answer?: string | null;
	error?: string | null;
	aborted?: boolean;
}

export interface MessageAgentDetails {
	agentHandle: string;
	messageId: string | null;
	status: "accepted" | "unknown";
	error?: string | null;
}

export interface CancelAgentDetails {
	agentHandle: string;
	status: CancelAckFrame["status"];
	error?: string | null;
}

export interface MessageStatusDetails {
	messageId: string;
	status: MessageStatusResultFrame["status"];
	error?: string | null;
	createdAt: string | null;
	sentAt: string | null;
	queuedAt: string | null;
	failedAt: string | null;
	aborted?: boolean;
}

export interface PublicListAgentItem {
	agentHandle: string;
	agentType: string | null;
	role: string;
	sessionName: string | null;
	task: string | null;
	depth: number;
	status: "pending" | "running" | "completed" | "failed" | "idle";
	awaitable: boolean;
}

export interface ListAgentsDetails {
	agents: PublicListAgentItem[];
}

export interface WaitHandleResult {
	agentHandle: string;
	status: "completed" | "failed" | "running" | "unknown";
	result: string | null;
	error: string | null;
}

export interface WaitDetails {
	items: WaitHandleResult[];
	aborted?: boolean;
}

export const DispatchAgentParams = Type.Object({
	agent: Type.Optional(Type.String({ description: "Agent definition name" })),
	task: Type.String({ description: "Task description" }),
	name: Type.Optional(Type.String({ description: "Name suffix (auto-generated prefix)" })),
	agent_handle: Type.Optional(Type.String({ description: "Existing agent handle to retask" })),
});

export const AskAgentParams = Type.Object({
	agent_handle: Type.String({ description: "Target messageable/askable agent handle to ask" }),
	question: Type.String({ description: "Question to ask the target agent" }),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

export const MessageAgentParams = Type.Object({
	agent_handle: Type.String({ description: "Target messageable agent handle" }),
	message: Type.String({ description: "One-way message to persistently deliver to the target agent" }),
	interrupt: Type.Optional(
		Type.Boolean({ description: "Deliver as an interrupt/steer message instead of a follow-up" }),
	),
});

export const CancelAgentParams = Type.Object({
	agent_handle: Type.String({ description: "Agent handle to cancel (must be an agent you dispatched)" }),
});

export const MessageStatusParams = Type.Object({
	message_id: Type.String({ description: "Message id returned by message_agent" }),
	wait_until_delivery: Type.Optional(
		Type.Boolean({ description: "Wait until delivery reaches queued, failed, unavailable, or unknown" }),
	),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 30 })),
});

const AgentHandlesParam = Type.Union([
	Type.String({ description: "Agent handle returned by dispatch_agent" }),
	Type.Array(Type.String({ description: "Agent handle returned by dispatch_agent" })),
]);

export const WaitForAgentParams = Type.Object({
	agent_handles: Type.Optional(AgentHandlesParam),
	handles: Type.Optional(AgentHandlesParam),
	timeout_s: Type.Optional(Type.Number({ minimum: 1, default: 600 })),
});

export const ListAgentsParams = Type.Object({
	awaitable: Type.Optional(
		Type.Boolean({
			description: "Filter to agents currently awaitable by this caller",
		}),
	),
});

export function normalizeHandles(input: string | string[] | undefined): string[] {
	if (input === undefined) return [];
	const values = Array.isArray(input) ? input : [input];
	return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

export function preview(text: string | null | undefined, limit = 80): string {
	if (!text) return "";
	const compact = text.replace(/\s+/g, " ").trim();
	return compact.length > limit ? `${compact.slice(0, limit)}…` : compact;
}

export function buildAskAgentTitle(agentHandle: string, question: string): string {
	return `(ask → ${agentHandle}) ${preview(question, 60)}`;
}

export function requireAgentsSkillMessage(action: string): string {
	return `Load the agents skill first: call skill({ name: "agents" }) before ${action}.`;
}

export function hasText(value: string | null | undefined): value is string {
	return value !== null && value !== undefined && value.trim() !== "";
}

function messageStatusDisplay(status: MessageStatusDetails["status"]): string {
	return status === "queued" ? "queued in recipient session" : status;
}

export function formatMessageStatusLine(details: MessageStatusDetails): string {
	const parts = [`message_id ${details.messageId}`, `status ${messageStatusDisplay(details.status)}`];
	if (hasText(details.error)) parts.push(`error ${details.error}`);
	return parts.join(" • ");
}

export function formatMessageStatusContent(details: MessageStatusDetails): string {
	const lines = [formatMessageStatusLine(details)];
	if (details.createdAt) lines.push(`created_at: ${details.createdAt}`);
	if (details.sentAt) lines.push(`sent_at: ${details.sentAt}`);
	if (details.queuedAt) lines.push(`queued_at: ${details.queuedAt}`);
	if (details.failedAt) lines.push(`failed_at: ${details.failedAt}`);
	return lines.join("\n");
}

export function formatWaitItemText(item: WaitHandleResult): string {
	if (item.status === "completed") {
		return `✓ ${item.agentHandle} completed\n${hasText(item.result) ? item.result : "(no output)"}`;
	}
	if (item.status === "failed") {
		const parts = [`✗ ${item.agentHandle} failed`, `error:\n${hasText(item.error) ? item.error : "unknown error"}`];
		if (hasText(item.result)) parts.push(`result:\n${item.result}`);
		return parts.join("\n");
	}
	if (item.status === "unknown") return `? ${item.agentHandle} not awaitable or unavailable`;
	return `… ${item.agentHandle} still running (timed out)`;
}

export function publicAgentHandle(agent: ListAgentItem): string | null {
	const handle = agent.agent_handle?.trim();
	if (!handle || handle === agent.agent_id) return null;
	return handle;
}

export function storedAgentType(agent: ListAgentItem): string | null {
	const value = agent.agent_type?.trim();
	return value ? value : null;
}

function publicSessionName(agent: ListAgentItem, agentHandle: string): string | null {
	const sessionName = agent.session_name.trim();
	if (!sessionName || sessionName === agent.agent_id || sessionName === agentHandle) return null;
	const publicName = sessionName.replaceAll(agent.agent_id, agentHandle).trim();
	return publicName && publicName !== agentHandle ? publicName : null;
}

function publicAgentTask(agent: ListAgentItem): string | null {
	const value = agent.task?.trim();
	return value ? value : null;
}

export function agentIdentity(agent: PublicListAgentItem): string {
	return agent.agentType ? `${agent.agentHandle} (${agent.agentType})` : agent.agentHandle;
}

export function toPublicListAgent(agent: ListAgentItem): PublicListAgentItem | null {
	const agentHandle = publicAgentHandle(agent);
	if (!agentHandle) return null;
	return {
		agentHandle,
		agentType: storedAgentType(agent),
		role: agent.role,
		sessionName: publicSessionName(agent, agentHandle),
		task: publicAgentTask(agent),
		depth: agent.depth,
		status: agent.status,
		awaitable: agent.awaitable,
	};
}

function buildListAgentLine(agent: PublicListAgentItem): string {
	const awaitableText = agent.awaitable ? "awaitable" : "not awaitable";
	const lines = [agentIdentity(agent), `${agent.status} • ${awaitableText} • ${agent.role} • depth ${agent.depth}`];
	if (hasText(agent.task)) lines.push(`task: ${agent.task}`);
	if (hasText(agent.sessionName) && agent.sessionName !== agentIdentity(agent))
		lines.push(`title: ${agent.sessionName}`);
	return lines.join("\n");
}

export function shortListAgentsSummary(agents: PublicListAgentItem[]): string {
	if (agents.length === 0) return "No agents found in this scope.";
	return agents.map((agent) => buildListAgentLine(agent)).join("\n\n");
}
