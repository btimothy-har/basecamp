import { randomUUID } from "node:crypto";
import { type DaemonConnection, waitForFrame } from "../../hub/index.ts";
import type {
	AttachWorkstreamAgentAckFrame,
	CancelAckFrame,
	CreateWorkstreamAckFrame,
	Frame,
	ListAgentItem,
	MessageStatusResultFrame,
	OutboundFrame,
	PeerMessageAckFrame,
	ReviseWorkstreamAckFrame,
	UpdateWorkstreamAckFrame,
	WaitResultFrame,
	WaitResultItem,
	WorkstreamAgentStatus,
} from "../../hub/protocol/index.ts";

export interface DaemonDispatchFrameOptions {
	agentId: string;
	agentHandle: string;
	agentType: string;
	model?: string | null;
	argv: string[];
	task: string;
	cwd: string;
	env: Record<string, string>;
	resumePath?: string | null;
	forkFrom?: string | null;
	// The run's own workspace; the daemon force-removes it when the run exits.
	ownedWorktree?: string | null;
	// The run's branch (`agent/<handle>`; null for detached ask workspaces) and the commit
	// OID it started from. Teardown deletes the branch only when this run minted it
	// (branchCreated) and it gained no commits past branchBase.
	ownedBranch?: string | null;
	branchBase?: string | null;
	branchCreated?: boolean;
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

export type ReviseWorkstreamResult = Pick<ReviseWorkstreamAckFrame, "status" | "version" | "error">;

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
	reviseWorkstream(input: {
		workstream: string;
		label: string;
		brief: string;
		constraints?: string | null;
	}): Promise<ReviseWorkstreamResult>;
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

/**
 * Send a request frame and await its correlated ack, collapsing the
 * randomUUID → send → waitForFrame(request_id match) round-trip shared by every
 * request/ack RPC. (dispatch correlates on run_id and waitForAgents on a custom
 * result-set predicate, so both stay bespoke.)
 */
async function requestAck<T extends Frame["type"]>(
	connection: DaemonConnection,
	ackType: T,
	request: OutboundFrame & { request_id: string },
	signal?: AbortSignal,
): Promise<Extract<Frame, { type: T }>> {
	connection.send(request);
	return waitForFrame(
		connection,
		ackType,
		(frame) => (frame as { request_id: string }).request_id === request.request_id,
		signal,
	);
}

export function createDaemonClient(connection: DaemonConnection): DaemonClient {
	return {
		dispatchAgent: async (input) => {
			const runId = randomUUID();
			connection.send({
				type: "dispatch",
				run_id: runId,
				agent_id: input.agentId,
				agent_handle: input.agentHandle,
				agent_type: input.agentType,
				model: input.model ?? null,
				spec: {
					argv: input.argv,
					task: input.task,
					cwd: input.cwd,
					env: input.env,
					resume_path: input.resumePath ?? null,
					fork_from: input.forkFrom ?? null,
					owned_worktree: input.ownedWorktree ?? null,
					owned_branch: input.ownedBranch ?? null,
					branch_base: input.branchBase ?? null,
					branch_created: input.branchCreated ?? false,
				},
			});

			const ack = await waitForFrame(connection, "dispatch_ack", (frame) => frame.run_id === runId);
			return {
				status: ack.status,
				reason: ack.reason,
			};
		},
		listAgents: async (input) => {
			const frame = await requestAck(connection, "list_agents_result", {
				type: "list_agents",
				request_id: randomUUID(),
				awaitable: Boolean(input.awaitable),
			});
			return frame.agents;
		},
		waitForAgents: async (input) => {
			const requested = new Set(input.agentHandles);
			connection.send({
				type: "wait",
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
			const ack = await requestAck(connection, "peer_message_ack", {
				type: "peer_message",
				request_id: randomUUID(),
				target_handle: input.targetHandle,
				message: input.message,
				interrupt: Boolean(input.interrupt),
			});
			return { message_id: ack.message_id, status: ack.status, error: ack.error };
		},
		cancelAgent: async (input) => {
			const ack = await requestAck(connection, "cancel_ack", {
				type: "cancel",
				request_id: randomUUID(),
				target_handle: input.targetHandle,
			});
			return { status: ack.status, error: ack.error };
		},
		messageStatus: async (input) => {
			const frame = await requestAck(
				connection,
				"message_status_result",
				{
					type: "message_status",
					request_id: randomUUID(),
					message_id: input.messageId,
					wait_until_delivery: Boolean(input.waitUntilDelivery),
					timeout_s: input.timeoutS,
				},
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
			const ack = await requestAck(connection, "create_workstream_ack", {
				type: "create_workstream",
				request_id: randomUUID(),
				workstream_id: input.workstreamId,
				slug: input.slug,
				label: input.label,
				brief: input.brief,
				source_dossier_path: input.sourceDossierPath,
				constraints: input.constraints ?? null,
				source_repo_page_path: input.sourceRepoPagePath ?? null,
			});
			return { status: ack.status, workstream_id: ack.workstream_id, slug: ack.slug, error: ack.error };
		},
		attachWorkstreamAgent: async (input) => {
			const ack = await requestAck(connection, "attach_workstream_agent_ack", {
				type: "attach_workstream_agent",
				request_id: randomUUID(),
				workstream: input.workstream,
				repo: input.repo ?? null,
				worktree_label: input.worktreeLabel ?? null,
				status: input.status,
				error: input.error ?? null,
			});
			return { status: ack.status, error: ack.error };
		},
		updateWorkstream: async (input) => {
			const ack = await requestAck(connection, "update_workstream_ack", {
				type: "update_workstream",
				request_id: randomUUID(),
				workstream: input.workstream,
				status: input.status,
			});
			return { status: ack.status, error: ack.error };
		},
		reviseWorkstream: async (input) => {
			const ack = await requestAck(connection, "revise_workstream_ack", {
				type: "revise_workstream",
				request_id: randomUUID(),
				workstream: input.workstream,
				label: input.label,
				brief: input.brief,
				constraints: input.constraints ?? null,
			});
			return { status: ack.status, version: ack.version, error: ack.error };
		},
	};
}
