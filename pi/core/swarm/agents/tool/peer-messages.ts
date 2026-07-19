import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { DaemonConnection } from "../../../hub/index.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	type DaemonToolDeps,
	formatMessageStatusContent,
	formatMessageStatusLine,
	hasText,
	type MessageAgentDetails,
	MessageAgentParams,
	type MessageStatusDetails,
	MessageStatusParams,
	requireAgentsSkillMessage,
} from "./support.ts";

export function registerPeerMessageTools(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<DaemonToolDeps, "hasInvokedSkill">,
): void {
	pi.registerTool({
		name: "message_agent",
		label: "Message Agent",
		description:
			"Send a one-way persistent message to an agent by its known public handle. A known public handle is a routable contact address, so this can reach an agent across sessions even without a live parent/child/sibling relationship. Returns daemon acceptance only; no recipient response is included.",
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
					content: [{ type: "text", text: "basecamp hub is not connected; cannot message agents." }],
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
				const text = hasText(ack.error) ? ack.error : "No available agent for that handle.";
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
					content: [{ type: "text", text: "basecamp hub is not connected; cannot check message status." }],
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
