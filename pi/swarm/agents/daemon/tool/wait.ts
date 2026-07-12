import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { DaemonConnection } from "#core/hub/index.ts";
import type { WaitResultFrame } from "#core/hub/protocol/index.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	type DaemonToolDeps,
	formatWaitItemText,
	normalizeHandles,
	preview,
	type WaitDetails,
	WaitForAgentParams,
	type WaitHandleResult,
} from "./support.ts";

export function registerWaitForAgentTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: DaemonToolDeps,
): void {
	pi.registerTool({
		name: "wait_for_agent",
		label: "Wait For Agent",
		description: "Wait for one or more awaitable async agent handles to complete.",
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
					content: [{ type: "text", text: "basecamp hub is not connected; cannot wait for async agent handles." }],
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
					return `${theme.fg("warning", "?")} ${item.agentHandle} ${theme.fg("muted", "not awaitable or unavailable")}`;
				}
				return `${theme.fg("warning", "…")} ${item.agentHandle} ${theme.fg("muted", "still running (timed out)")}`;
			});
			return new Text(lines.join("\n"), 0, 0);
		},
	});
}
