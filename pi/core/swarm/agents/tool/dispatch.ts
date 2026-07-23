import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { errorMessage } from "../../../errors.ts";
import type { DaemonConnection } from "../../../hub/index.ts";
import { buildAgentHandle } from "../../../hub/index.ts";
import { type AgentWorkspaceProvision, discardAgentWorkspace, provisionAgentWorkspace } from "../agent-workspace.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentLaunchSpec, buildAgentTitleBase, processEnvForSpawn, resolveParentSession } from "../launch.ts";
import { createDaemonClient, type DaemonDispatchResult } from "../rpc.ts";
import {
	type DaemonToolDeps,
	DispatchAgentParams,
	type DispatchDetails,
	publicAgentHandle,
	requireAgentsSkillMessage,
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
							text: requireAgentsSkillMessage("dispatching"),
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
			const workspaceState = deps.getWorkspaceState();
			const requestedAgentConfig = requestedAgent
				? (discoverAgents().find((candidate) => candidate.name === requestedAgent) ?? null)
				: null;

			// The branch is keyed to the agent handle, so provisioning happens per dispatch
			// attempt: a duplicate-handle rejection discards the workspace and re-provisions
			// under the next candidate handle. Only a successful dispatch keeps the workspace
			// (the running agent needs it); the daemon owns teardown from acceptance on.
			const attempts = requestedHandle ? 1 : 3;
			let agentHandle = requestedHandle ?? buildAgentHandle();
			let provision: AgentWorkspaceProvision | null = null;
			let result: DaemonDispatchResult | null = null;
			let agentLabel = requestedAgent ?? "ad-hoc";
			let dispatched = false;
			try {
				for (let attempt = 0; attempt < attempts; attempt++) {
					provision = await provisionAgentWorkspace(
						pi,
						{
							kind: "dispatch",
							agentHandle,
							isRetask: Boolean(requestedHandle),
							runToken: localId,
							agentName: requestedAgent ?? "adhoc",
						},
						workspaceState,
					);

					const agentLaunch = buildAgentLaunchSpec({
						pi,
						getAgents: discoverAgents,
						resolvedAgent: requestedAgentConfig,
						basecampExtensionRoot: deps.basecampExtensionRoot,
						agentId,
						requestedAgent,
						namePrefix,
						nameSuffix: params.name,
						task: params.task,
						modelContext: ctx.model,
						resolveModelAlias: deps.resolveModelAlias,
						workspace: workspaceState,
						parentSession: resolveParentSession(pi, ctx),
						project: process.env.BASECAMP_PROJECT ?? "default",
						agentWorkspace: provision,
					});
					if (!agentLaunch.ok) {
						return { content: [{ type: "text", text: agentLaunch.message }], isError: true, details: null };
					}

					const { plan } = agentLaunch;
					agentLabel = plan.agentLabel ?? "ad-hoc";
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

					result = await daemonClient.dispatchAgent({
						agentId,
						agentHandle,
						agentType: agentLabel,
						model: plan.model ?? "default",
						argv: plan.args.slice(0, -1),
						task: taskSpec,
						cwd: plan.spawnCwd,
						env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
						ownedWorktree: provision?.worktreeDir ?? null,
						ownedBranch: provision?.branch ?? null,
						branchBase: provision?.baseOid ?? null,
						branchCreated: provision?.branchCreated ?? false,
					});

					if (result.status !== "rejected" || result.reason !== "duplicate_agent_handle" || attempt === attempts - 1) {
						break;
					}
					await discardAgentWorkspace(pi, provision);
					provision = null;
					agentHandle = buildAgentHandle();
				}

				if (!result || result.status === "rejected") {
					return {
						content: [{ type: "text", text: `dispatch rejected: ${result?.reason ?? "unknown"}` }],
						isError: true,
						details: { agentHandle, agent: agentLabel } satisfies DispatchDetails,
					};
				}

				dispatched = true;
				const setupNote = provision?.setupWarning ? `\n⚠ ${provision.setupWarning}` : "";
				const branchNote = provision
					? ` → branch \`${provision.branch}\` (when it finishes, \`git merge\` it to integrate; retasking the handle continues the same branch)`
					: "";
				return {
					content: [
						{ type: "text", text: `⏳ dispatched ${agentLabel} — handle ${agentHandle}${branchNote}${setupNote}` },
					],
					details: { agentHandle, agent: agentLabel } satisfies DispatchDetails,
				};
			} catch (error) {
				const msg = errorMessage(error);
				return { content: [{ type: "text", text: msg }], isError: true, details: null };
			} finally {
				if (!dispatched) await discardAgentWorkspace(pi, provision);
			}
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
