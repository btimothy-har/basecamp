import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import { resolveAliasedModel } from "pi-core/platform/model-resolution.ts";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { createDaemonClient } from "../daemon/client.ts";
import { dispatchWithHandleRetry } from "../daemon/dispatch-retry.ts";
import { buildAgentHandle } from "../daemon/handles.ts";
import { getActiveDaemonConnection } from "../daemon/index.ts";
import { discoverAgents } from "../discovery.ts";
import { errorMessage } from "../errors.ts";
import { buildAgentLaunchSpec, processEnvForSpawn } from "../launch.ts";
import { annotateFindings } from "./annotate-pane.ts";
import { isSubagent, persistReviewArtifact } from "./command-helpers.ts";
import { formatReviewPrompt } from "./format.ts";
import { type OrchestrateDeps, REVIEWERS, type ReviewerSpec, type ReviewScope, runReview } from "./orchestrate.ts";
import { transposeReport } from "./transpose.ts";

async function resolveDefaultBase(pi: ExtensionAPI, cwd: string): Promise<string> {
	const head = await exec(pi, "git", ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], { cwd });
	const ref = head.stdout.trim();
	return ref.startsWith("origin/") ? ref.slice("origin/".length) : "main";
}

async function resolveCurrentBranch(pi: ExtensionAPI, cwd: string): Promise<string> {
	const branch = await exec(pi, "git", ["branch", "--show-current"], { cwd });
	return branch.stdout.trim() || "HEAD";
}

export function registerReviewCommand(pi: ExtensionAPI, deps: PiSwarmDependencies): void {
	pi.registerCommand("code-review", {
		description: "Run an independent multi-agent code review of the current branch",
		handler: async (args: string, ctx: ExtensionCommandContext) => {
			try {
				if (isSubagent()) {
					ctx.ui.notify(
						"Code review is disabled in subagents; run /code-review from the top-level session.",
						"warning",
					);
					return;
				}

				const connection = getActiveDaemonConnection();
				if (!connection) {
					ctx.ui.notify("basecamp swarm daemon not connected; cannot run code review.", "error");
					return;
				}
				const daemonClient = createDaemonClient(connection);

				const cwd = ctx.cwd;
				const trimmedArgs = args.trim();
				const base = trimmedArgs || (await resolveDefaultBase(pi, cwd));
				if (base.startsWith("-")) {
					ctx.ui.notify(`Invalid base ref: ${base}`, "error");
					return;
				}
				const currentBranch = await resolveCurrentBranch(pi, cwd);
				const diff = await exec(pi, "git", ["diff", "--quiet", `${base}...HEAD`], { cwd });
				if (diff.code === 0) {
					ctx.ui.notify(`No changes to review between ${base} and HEAD.`, "info");
					return;
				}
				if (diff.code !== 1) {
					throw new Error(diff.stderr.trim() || `git diff failed with exit code ${diff.code}`);
				}

				const transposer = await resolveAliasedModel(ctx, "fast");
				if (!transposer) {
					ctx.ui.notify("Review transposer model (fast) unavailable; aborting.", "error");
					return;
				}

				const scope: ReviewScope = {
					base,
					head: "HEAD",
					cwd,
					label: `branch ${currentBranch} → ${base}`,
				};

				ctx.ui.notify(`Running independent code review — dispatching ${REVIEWERS.length} reviewers…`, "info");

				async function dispatchReviewer(spec: ReviewerSpec, brief: string): Promise<string> {
					const agentId = randomUUID();
					const namePrefix = `review-${spec.dimension}`;
					const launch = buildAgentLaunchSpec({
						pi,
						getAgents: discoverAgents,
						basecampExtensionRoot: deps.basecampExtensionRoot,
						requestedAgent: spec.agent,
						namePrefix,
						task: brief,
						modelContext: ctx.model,
						resolveModelAlias: deps.resolveModelAlias,
						workspace: deps.getWorkspaceState(),
						agentId,
						parentSession:
							process.env.BASECAMP_SESSION_NAME ?? (pi.getSessionName()?.trim() || ctx.sessionManager.getSessionId()),
						project: process.env.BASECAMP_PROJECT ?? "default",
					});
					if (!launch.ok) throw new Error(launch.message);

					const { plan } = launch;
					const taskSpec = plan.args.at(-1);
					if (!taskSpec) throw new Error("Unable to build async task argument.");

					const dispatchEnv = {
						...processEnvForSpawn(),
						...plan.environment,
						BASECAMP_AGENT_TITLE: `(review → ${spec.dimension})`,
					};
					const { agentHandle, result: dispatchResult } = await dispatchWithHandleRetry(
						daemonClient,
						(agentHandle) => ({
							agentId,
							agentHandle,
							agentType: "review",
							runKind: plan.runKind,
							model: plan.model ?? "default",
							argv: plan.args.slice(0, -1),
							task: taskSpec,
							cwd: plan.spawnCwd,
							env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
						}),
						{ initialHandle: buildAgentHandle(), attempts: 3 },
					);

					if (!dispatchResult || dispatchResult.status === "rejected") {
						throw new Error(`dispatch rejected: ${dispatchResult?.reason ?? "unknown"}`);
					}

					return agentHandle;
				}

				const orchestrateDeps: OrchestrateDeps = {
					dispatchReviewer,
					waitForReviewers: async (handles) => {
						const results = await daemonClient.waitForAgents({
							agentHandles: handles,
							timeoutS: 600,
							signal: ctx.signal,
						});
						return new Map(
							results.map((result, index) => [
								result.agent_handle ?? handles[index] ?? "",
								{ status: result.status, result: result.result, error: result.error },
							]),
						);
					},
					transpose: async (prose, dimension) => {
						return transposeReport(prose, dimension, {
							model: transposer.model,
							auth: transposer.auth,
							signal: ctx.signal,
						});
					},
				};

				const outcome = await runReview(scope, orchestrateDeps);
				if (!outcome.ok) {
					ctx.ui.notify(
						`Code review failed: reviewer '${outcome.failedReviewer}' did not produce findings — ${outcome.reason}. No verdict was produced; re-run /code-review.`,
						"error",
					);
					return;
				}
				const result = outcome.result;

				let reactions: (string | null)[] | null = null;
				let annotated = false;
				if (ctx.hasUI) {
					const annotation = await annotateFindings(ctx.ui, result.findings);
					if (!annotation.cancelled) {
						reactions = annotation.reactions;
						annotated = true;
					}
				}

				const artifactPath = persistReviewArtifact(result, reactions);
				pi.sendUserMessage(formatReviewPrompt(result, artifactPath, annotated));
				ctx.ui.notify(
					`Code review complete: ${result.verdict.decision} (${result.findings.length} findings, ${annotated ? "annotated" : "not annotated"})`,
					"info",
				);
			} catch (error) {
				ctx.ui.notify(`Code review failed: ${errorMessage(error)}`, "error");
			}
		},
	});
}
