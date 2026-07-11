import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { discoverAgents } from "../../discovery.ts";
import { buildAgentLaunchSpec, buildAgentTitleBase, processEnvForSpawn } from "../../launch.ts";
import type { DaemonConnection } from "../connection.ts";
import { dispatchWithHandleRetry } from "../dispatch-retry.ts";
import { buildAgentHandle } from "../handles.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	type DaemonToolDeps,
	DispatchAgentParams,
	type DispatchDetails,
	publicAgentHandle,
	storedAgentType,
} from "./support.ts";

export function registerDispatchAgentTool(
	pi: ExtensionAPI,
	getConnection: () => Promise<DaemonConnection | null>,
	deps: DaemonToolDeps,
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
							text: "basecamp hub is not connected; dispatch cannot proceed.",
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

			const dispatchEnv = {
				...processEnvForSpawn(),
				...plan.environment,
				BASECAMP_AGENT_TITLE: buildAgentTitleBase(requestedAgent, params.task),
			};

			const attempts = requestedHandle ? 1 : 3;
			const { agentHandle, result } = await dispatchWithHandleRetry(
				daemonClient,
				(agentHandle) => ({
					agentId,
					agentHandle,
					agentType: plan.agentLabel ?? "ad-hoc",
					runKind: plan.runKind,
					model: plan.model ?? "default",
					argv: plan.args.slice(0, -1),
					task: taskSpec,
					cwd: plan.spawnCwd,
					env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
				}),
				{ initialHandle: requestedHandle ?? buildAgentHandle(), attempts },
			);

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
}
