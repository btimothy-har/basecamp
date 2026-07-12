import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { DaemonConnection } from "#core/hub/index.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	type CancelAgentDetails,
	CancelAgentParams,
	type DaemonToolDeps,
	requireAgentsSkillMessage,
} from "./support.ts";

export function registerCancelAgentTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: Pick<DaemonToolDeps, "hasInvokedSkill">,
): void {
	pi.registerTool({
		name: "cancel_agent",
		label: "Cancel Agent",
		description:
			"Cancel a running agent you dispatched, stopping it and its entire dispatched subtree. You can only cancel agents in your own dispatch subtree.",
		parameters: CancelAgentParams,
		async execute(_id, params) {
			if (!deps.hasInvokedSkill("agents")) {
				return {
					content: [{ type: "text", text: requireAgentsSkillMessage("cancelling agents") }],
					isError: true,
					details: null,
				};
			}
			const targetHandle = params.agent_handle.trim();
			if (!targetHandle) {
				return {
					content: [{ type: "text", text: "cancel_agent requires a non-empty agent_handle." }],
					isError: true,
					details: null,
				};
			}
			const connection = await getConnection();
			if (!connection) {
				return {
					content: [{ type: "text", text: "basecamp hub is not connected; cannot cancel agents." }],
					isError: true,
					details: null,
				};
			}

			const ack = await createDaemonClient(connection).cancelAgent({ targetHandle });
			const details: CancelAgentDetails = { agentHandle: targetHandle, status: ack.status, error: ack.error };
			if (ack.status === "cancelled") {
				return { content: [{ type: "text", text: `cancelled ${targetHandle}` }], details };
			}
			if (ack.status === "already_terminal") {
				return {
					content: [
						{
							type: "text",
							text: `${targetHandle} is not running (already finished or never started).`,
						},
					],
					details,
				};
			}
			if (ack.status === "not_found") {
				return {
					content: [{ type: "text", text: `No agent found for handle ${targetHandle}.` }],
					isError: true,
					details,
				};
			}
			return {
				content: [{ type: "text", text: "You can only cancel agents you dispatched." }],
				isError: true,
				details,
			};
		},
		renderResult(result, _opts, theme) {
			const details = result.details as CancelAgentDetails | null;
			const message = result.content[0]?.type === "text" ? result.content[0].text : "";
			if (!details) return new Text(message, 0, 0);
			if (details.status === "cancelled")
				return new Text(theme.fg("accent", message || `cancelled ${details.agentHandle}`), 0, 0);
			if (details.status === "already_terminal") return new Text(theme.fg("warning", message), 0, 0);
			return new Text(theme.fg("error", message), 0, 0);
		},
	});
}
