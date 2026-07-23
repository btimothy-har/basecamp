import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { errorMessage } from "../../../errors.ts";
import type { DaemonConnection } from "../../../hub/index.ts";
import { buildAgentHandle } from "../../../hub/index.ts";
import type { WaitResultFrame } from "../../../hub/protocol/index.ts";
import { type AgentWorkspaceProvision, discardAgentWorkspace, provisionAgentWorkspace } from "../agent-workspace.ts";
import { discoverAgents } from "../discovery.ts";
import { dispatchWithHandleRetry } from "../dispatch-retry.ts";
import { buildAgentLaunchSpec, processEnvForSpawn, resolveParentSession } from "../launch.ts";
import { createDaemonClient } from "../rpc.ts";
import {
	AskAgentParams,
	type AskDetails,
	buildAskAgentTitle,
	type DaemonToolDeps,
	hasText,
	preview,
	requireAgentsSkillMessage,
} from "./support.ts";

type AskToolResult = {
	content: Array<{ type: "text"; text: string }>;
	isError?: boolean;
	details: AskDetails;
};

async function awaitAnswer(
	daemonClient: ReturnType<typeof createDaemonClient>,
	agentHandle: string,
	timeoutParam: number | undefined,
	signal: AbortSignal | undefined,
): Promise<AskToolResult> {
	const timeoutS = Math.max(1, Math.floor(timeoutParam ?? 600));
	let waitResults: WaitResultFrame["results"];
	try {
		waitResults = await daemonClient.waitForAgents({ agentHandles: [agentHandle], timeoutS, signal });
	} catch (error) {
		if (signal?.aborted || (error instanceof Error && error.message === "aborted")) {
			return {
				content: [{ type: "text", text: "ask aborted" }],
				details: { agentHandle, status: "running", aborted: true },
			};
		}
		throw error;
	}

	const answer = waitResults[0];
	if (answer?.status === "completed") {
		return {
			content: [{ type: "text", text: answer.result ?? "" }],
			details: { agentHandle, status: "completed", answer: answer.result },
		};
	}
	if (answer?.status === "failed") {
		const message = hasText(answer.error) ? answer.error : "ask failed";
		return {
			content: [{ type: "text", text: message }],
			isError: true,
			details: { agentHandle, status: "failed", answer: answer.result, error: answer.error },
		};
	}
	if (answer?.status === "running") {
		const message = "timed out waiting for answer";
		return { content: [{ type: "text", text: message }], details: { agentHandle, status: "running", error: message } };
	}
	return { content: [{ type: "text", text: "No answer available." }], details: { agentHandle, status: "unknown" } };
}

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
							text: requireAgentsSkillMessage("asking agents"),
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
			const runToken = randomUUID().slice(0, 6);
			const namePrefix = `ask-${runToken}`;

			// The answerer gets a detached workspace at the target's branch tip (its committed
			// work) or the parent's HEAD/snapshot. Keyed to the immutable target handle, so it
			// is stable across duplicate-handle retries. The daemon owns teardown on acceptance.
			let provision: AgentWorkspaceProvision | null = null;
			let accepted = false;
			try {
				provision = await provisionAgentWorkspace(
					pi,
					{ kind: "ask", targetHandle, runToken, agentName: "ask" },
					deps.getWorkspaceState(),
				);

				const agentLaunch = buildAgentLaunchSpec({
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
					parentSession: resolveParentSession(pi, ctx),
					project: process.env.BASECAMP_PROJECT ?? "default",
					agentWorkspace: provision,
				});
				if (!agentLaunch.ok) {
					return { content: [{ type: "text", text: agentLaunch.message }], isError: true, details: null };
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
						model: plan.model ?? "default",
						argv: plan.args.slice(0, -1),
						task: taskSpec,
						cwd: plan.spawnCwd,
						env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
						forkFrom: targetHandle,
						ownedWorktree: provision?.worktreeDir ?? null,
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
				accepted = true;
				return await awaitAnswer(daemonClient, agentHandle, params.timeout_s, signal);
			} finally {
				if (!accepted) await discardAgentWorkspace(pi, provision);
			}
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
