import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import type { DaemonConnection } from "../../../hub/index.ts";
import { buildAgentHandle } from "../../../hub/index.ts";
import type { WaitResultFrame } from "../../../hub/protocol/index.ts";
import { discoverAgents } from "../discovery.ts";
import { dispatchWithHandleRetry } from "../dispatch-retry.ts";
import { buildAgentLaunchSpec, processEnvForSpawn } from "../launch.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	AskAgentParams,
	type AskDetails,
	buildAskAgentTitle,
	type DaemonToolDeps,
	hasText,
	preview,
} from "./support.ts";

export function registerAskAgentTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: DaemonToolDeps,
): void {
	pi.registerTool({
		name: "ask_agent",
		label: "Ask Agent",
		description:
			"Ask an agent by its known public handle and return its answer. A known public handle is a routable contact address, so this can reach an agent across sessions even without a live parent/child/sibling relationship.",
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
							text: "basecamp hub is not connected; dispatch cannot proceed.",
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

			const dispatchEnv = {
				...processEnvForSpawn(),
				...plan.environment,
				BASECAMP_AGENT_TITLE: buildAskAgentTitle(targetHandle, params.question),
			};
			const { agentHandle, result } = await dispatchWithHandleRetry(
				daemonClient,
				(agentHandle) => ({
					agentId,
					agentHandle,
					agentType: "ask",
					runKind: plan.runKind,
					model: plan.model ?? "default",
					argv: plan.args.slice(0, -1),
					task: taskSpec,
					cwd: plan.spawnCwd,
					env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
					forkFrom: targetHandle,
				}),
				{ initialHandle: buildAgentHandle(), attempts: 3 },
			);

			if (!result || result.status === "rejected") {
				const message =
					result?.reason === "fork_target_unknown"
						? "No available agent for that handle."
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
