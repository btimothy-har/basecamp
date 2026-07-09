import { randomUUID } from "node:crypto";
import { type DaemonConnection, waitForFrame } from "./connection.ts";
import type {
	AttachWorkstreamAgentAckFrame,
	CancelAckFrame,
	CreateWorkstreamAckFrame,
	ListAgentItem,
	MessageStatusResultFrame,
	PeerMessageAckFrame,
	UpdateWorkstreamAckFrame,
	WaitResultFrame,
	WaitResultItem,
	WorkstreamAgentStatus,
} from "./frames/index.ts";
import { PROTOCOL_VERSION } from "./frames/index.ts";

export interface DaemonDispatchFrameOptions {
	agentId: string;
	agentHandle: string;
	agentType: string;
	runKind: string;
	model?: string | null;
	argv: string[];
	task: string;
	cwd: string;
	env: Record<string, string>;
	resumePath?: string | null;
	forkFrom?: string | null;
}

export interface DaemonDispatchResult {
	status: "spawned" | "rejected";
	reason?: string | null;
}

export interface SendPeerMessageOptions {
	targetHandle: string;
	message: string;
	interrupt?: boolean;
}

export interface MessageStatusOptions {
	messageId: string;
	waitUntilDelivery?: boolean;
	timeoutS?: number;
	signal?: AbortSignal;
}

export type SendPeerMessageResult = Pick<PeerMessageAckFrame, "message_id" | "status" | "error">;

export type CancelAgentResult = Pick<CancelAckFrame, "status" | "error">;

export type CreateWorkstreamResult = Pick<CreateWorkstreamAckFrame, "status" | "workstream_id" | "slug" | "error">;

export type AttachWorkstreamAgentResult = Pick<AttachWorkstreamAgentAckFrame, "status" | "error">;

export type UpdateWorkstreamResult = Pick<UpdateWorkstreamAckFrame, "status" | "error">;

export type MessageStatusResult = Pick<
	MessageStatusResultFrame,
	"message_id" | "status" | "error" | "created_at" | "sent_at" | "queued_at" | "failed_at"
>;

export interface DaemonClient {
	dispatchAgent(options: DaemonDispatchFrameOptions): Promise<DaemonDispatchResult>;
	listAgents(input: { awaitable?: boolean }): Promise<ListAgentItem[]>;
	waitForAgents(input: {
		agentHandles: string[];
		timeoutS: number;
		signal?: AbortSignal;
	}): Promise<WaitResultFrame["results"]>;
	sendPeerMessage(input: SendPeerMessageOptions): Promise<SendPeerMessageResult>;
	cancelAgent(input: { targetHandle: string }): Promise<CancelAgentResult>;
	messageStatus(input: MessageStatusOptions): Promise<MessageStatusResult>;
	createWorkstream(input: {
		workstreamId: string;
		slug: string;
		label: string;
		brief: string;
		sourceDossierPath: string;
		constraints?: string | null;
		sourceRepoPagePath?: string | null;
	}): Promise<CreateWorkstreamResult>;
	attachWorkstreamAgent(input: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: WorkstreamAgentStatus;
		error?: string | null;
	}): Promise<AttachWorkstreamAgentResult>;
	updateWorkstream(input: { workstream: string; status: "open" | "closed" }): Promise<UpdateWorkstreamResult>;
}

function hasAgentHandle(result: WaitResultItem): result is WaitResultItem & { agent_handle: string } {
	return typeof result.agent_handle === "string";
}

function sameAsRequested(resultAgentHandles: string[], requestedSet: Set<string>): boolean {
	const resultSet = new Set(resultAgentHandles);
	if (resultSet.size !== requestedSet.size) return false;
	return [...requestedSet].every((agentHandle) => resultSet.has(agentHandle));
}

function dedupeRequestedResults(
	results: WaitResultFrame["results"],
	requested: Set<string>,
): WaitResultFrame["results"] {
	const requestedMap = new Map(
		results
			.filter((result) => hasAgentHandle(result) && requested.has(result.agent_handle))
			.map((result) => [result.agent_handle, result]),
	);
	const deduped: WaitResultFrame["results"] = [];
	for (const agentHandle of requested) {
		deduped.push(
			requestedMap.get(agentHandle) ?? { agent_handle: agentHandle, status: "unknown", result: null, error: null },
		);
	}
	return deduped;
}

export function createDaemonClient(connection: DaemonConnection): DaemonClient {
	return {
		dispatchAgent: async (input) => {
			const runId = randomUUID();
			connection.send({
				type: "dispatch",
				v: PROTOCOL_VERSION,
				run_id: runId,
				agent_id: input.agentId,
				agent_handle: input.agentHandle,
				agent_type: input.agentType,
				run_kind: input.runKind,
				model: input.model ?? null,
				spec: {
					argv: input.argv,
					task: input.task,
					cwd: input.cwd,
					env: input.env,
					resume_path: input.resumePath ?? null,
					fork_from: input.forkFrom ?? null,
				},
			});

			const ack = await waitForFrame(connection, "dispatch_ack", (frame) => frame.run_id === runId);
			return {
				status: ack.status,
				reason: ack.reason,
			};
		},
		listAgents: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "list_agents",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				awaitable: Boolean(input.awaitable),
			});
			const frame = await waitForFrame(
				connection,
				"list_agents_result",
				(response) => response.request_id === requestId,
			);
			return frame.agents;
		},
		waitForAgents: async (input) => {
			const requested = new Set(input.agentHandles);
			connection.send({
				type: "wait",
				v: PROTOCOL_VERSION,
				agent_ids: [],
				agent_handles: input.agentHandles,
				mode: "all",
				timeout_s: input.timeoutS,
			});
			const frame = await waitForFrame(
				connection,
				"wait_result",
				(candidate) =>
					sameAsRequested(
						candidate.results.filter(hasAgentHandle).map((result) => result.agent_handle),
						requested,
					),
				input.signal,
			);
			return dedupeRequestedResults(frame.results, requested);
		},
		sendPeerMessage: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "peer_message",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				target_handle: input.targetHandle,
				message: input.message,
				interrupt: Boolean(input.interrupt),
			});
			const ack = await waitForFrame(connection, "peer_message_ack", (frame) => frame.request_id === requestId);
			return {
				message_id: ack.message_id,
				status: ack.status,
				error: ack.error,
			};
		},
		cancelAgent: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "cancel",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				target_handle: input.targetHandle,
			});
			const ack = await waitForFrame(connection, "cancel_ack", (frame) => frame.request_id === requestId);
			return {
				status: ack.status,
				error: ack.error,
			};
		},
		messageStatus: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "message_status",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				message_id: input.messageId,
				wait_until_delivery: Boolean(input.waitUntilDelivery),
				timeout_s: input.timeoutS,
			});
			const frame = await waitForFrame(
				connection,
				"message_status_result",
				(response) => response.request_id === requestId,
				input.signal,
			);
			return {
				message_id: frame.message_id,
				status: frame.status,
				error: frame.error,
				created_at: frame.created_at,
				sent_at: frame.sent_at,
				queued_at: frame.queued_at,
				failed_at: frame.failed_at,
			};
		},
		createWorkstream: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "create_workstream",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				workstream_id: input.workstreamId,
				slug: input.slug,
				label: input.label,
				brief: input.brief,
				source_dossier_path: input.sourceDossierPath,
				constraints: input.constraints ?? null,
				source_repo_page_path: input.sourceRepoPagePath ?? null,
			});
			const ack = await waitForFrame(connection, "create_workstream_ack", (frame) => frame.request_id === requestId);
			return {
				status: ack.status,
				workstream_id: ack.workstream_id,
				slug: ack.slug,
				error: ack.error,
			};
		},
		attachWorkstreamAgent: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "attach_workstream_agent",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				workstream: input.workstream,
				repo: input.repo ?? null,
				worktree_label: input.worktreeLabel ?? null,
				status: input.status,
				error: input.error ?? null,
			});
			const ack = await waitForFrame(
				connection,
				"attach_workstream_agent_ack",
				(frame) => frame.request_id === requestId,
			);
			return {
				status: ack.status,
				error: ack.error,
			};
		},
		updateWorkstream: async (input) => {
			const requestId = randomUUID();
			connection.send({
				type: "update_workstream",
				v: PROTOCOL_VERSION,
				request_id: requestId,
				workstream: input.workstream,
				status: input.status,
			});
			const ack = await waitForFrame(connection, "update_workstream_ack", (frame) => frame.request_id === requestId);
			return {
				status: ack.status,
				error: ack.error,
			};
		},
	};
}
