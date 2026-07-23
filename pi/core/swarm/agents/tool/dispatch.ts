import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { errorMessage } from "../../../errors.ts";
import type { DaemonConnection } from "../../../hub/index.ts";
import { buildAgentHandle } from "../../../hub/index.ts";
import { type AgentWorkspaceProvision, discardAgentWorkspace, provisionAgentWorkspace } from "../agent-workspace.ts";
import { discoverAgents } from "../discovery.ts";
import { dispatchWithHandleRetry } from "../dispatch-retry.ts";
import { buildAgentLaunchSpec, buildAgentTitleBase, processEnvForSpawn, resolveParentSession } from "../launch.ts";
import { createDaemonClient } from "../rpc.ts";
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

			const namePrefix = `agent-${randomUUID().slice(0, 6)}`;
			const workspaceState = deps.getWorkspaceState();
			const requestedAgentConfig = requestedAgent
				? (discoverAgents().find((candidate) => candidate.name === requestedAgent) ?? null)
				: null;
			// Deliverable-anchored posture: only a `deliverable: true` persona (worker) mints a
			// branch; every other persona and ad-hoc runs are branchless report runs.
			const kind = requestedAgentConfig?.deliverable ? ("deliverable" as const) : ("report" as const);

			// Deliverable branches are handle-keyed, so provisioning happens per dispatch attempt
			// with a fresh per-attempt worktree token: a duplicate-handle rejection discards the
			// workspace and re-provisions under the next candidate handle. Only a successful
			// dispatch keeps the workspace; the daemon owns teardown from acceptance on.
			let provision: AgentWorkspaceProvision | null = null;
			let agentLabel = requestedAgent ?? "ad-hoc";
			let dispatched = false;
			// Whether the final attempt's dispatch frame reached the socket. Reset per attempt so it
			// reflects the last attempt only; a post-send failure leaves teardown to the daemon.
			let frameSent = false;
			// A daemon rejected-ack means no run was spawned, so the workspace is safe to discard
			// even though the frame was sent.
			let rejectedByDaemon = false;
			try {
				const { agentHandle, result } = await dispatchWithHandleRetry(
					daemonClient,
					async (candidateHandle) => {
						frameSent = false;
						const runToken = randomUUID().slice(0, 6);
						const agentName = requestedAgent ?? "adhoc";
						provision = await provisionAgentWorkspace(
							pi,
							kind === "deliverable"
								? { kind, agentHandle: candidateHandle, isRetask: Boolean(requestedHandle), runToken, agentName }
								: { kind, runToken, agentName },
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
						if (!agentLaunch.ok) throw new Error(agentLaunch.message);

						const { plan } = agentLaunch;
						agentLabel = plan.agentLabel ?? "ad-hoc";
						const taskSpec = plan.args.at(-1);
						if (!taskSpec) throw new Error("Unable to build async task argument.");

						const dispatchEnv = {
							...processEnvForSpawn(),
							...plan.environment,
							BASECAMP_AGENT_TITLE: buildAgentTitleBase(requestedAgent, params.task),
						};

						return {
							agentId,
							agentHandle: candidateHandle,
							agentType: agentLabel,
							model: plan.model ?? "default",
							argv: plan.args.slice(0, -1),
							task: taskSpec,
							cwd: plan.spawnCwd,
							env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: candidateHandle },
							ownedWorktree: provision?.worktreeDir ?? null,
							ownedBranch: provision?.branch ?? null,
							branchBase: provision?.baseOid ?? null,
							branchCreated: provision?.branchCreated ?? false,
							onSent: () => {
								frameSent = true;
							},
						};
					},
					{
						initialHandle: requestedHandle ?? buildAgentHandle(),
						attempts: requestedHandle ? 1 : 3,
						onRetry: async () => {
							await discardAgentWorkspace(pi, provision);
							provision = null;
						},
					},
				);

				if (!result || result.status === "rejected") {
					rejectedByDaemon = result?.status === "rejected";
					return {
						content: [{ type: "text", text: `dispatch rejected: ${result?.reason ?? "unknown"}` }],
						isError: true,
						details: { agentHandle, agent: agentLabel } satisfies DispatchDetails,
					};
				}

				dispatched = true;
				// The closure assigned this; TS's flow analysis cannot see across the callback.
				const live = provision as AgentWorkspaceProvision | null;
				const setupNote = live?.setupWarning ? `\n⚠ ${live.setupWarning}` : "";
				const branchNote = live?.branch
					? ` → branch \`${live.branch}\` (when it finishes, \`git merge\` it to integrate; retasking the handle continues the same branch)`
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
				// Discard only when the daemon cannot own the run: the frame never reached it
				// (pre-send failure) or it explicitly rejected (dispatched stays false, but a rejected
				// ack means no run was spawned). A post-send failure with no ack is ambiguous — the
				// daemon may have spawned the run — so leave teardown to its reap/reconcile chain.
				if (!dispatched && (!frameSent || rejectedByDaemon)) await discardAgentWorkspace(pi, provision);
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
