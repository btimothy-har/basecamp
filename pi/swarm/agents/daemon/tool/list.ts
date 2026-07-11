import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { DaemonConnection } from "../connection.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	agentIdentity,
	type DaemonToolDeps,
	type ListAgentsDetails,
	ListAgentsParams,
	type PublicListAgentItem,
	shortListAgentsSummary,
	toPublicListAgent,
} from "./support.ts";

export function registerListAgentsTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: DaemonToolDeps,
): void {
	pi.registerTool({
		name: "list_agents",
		label: "List Agents",
		description: "List visible dispatchable async agents under the caller's daemon root.",
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
					content: [{ type: "text", text: "basecamp hub is not connected; cannot list dispatchable agents." }],
					isError: true,
					details: null,
				};
			}

			const daemonClient = createDaemonClient(connection);
			const agents = (await daemonClient.listAgents({ awaitable: Boolean(params.awaitable) }))
				.map(toPublicListAgent)
				.filter((agent): agent is PublicListAgentItem => agent !== null);

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
				return `${agentIdentity(agent)} ${status} ${awaitable}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
