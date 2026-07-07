import { randomBytes, randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Model } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import { createDaemonClient } from "../daemon/client.ts";
import { buildAgentHandle } from "../daemon/handles.ts";
import { getActiveDaemonConnection } from "../daemon/index.ts";
import { discoverAgents } from "../discovery.ts";
import { buildAgentLaunchSpec, processEnvForSpawn } from "../launch.ts";
import { formatReviewPrompt } from "./format.ts";
import { type OrchestrateDeps, REVIEWERS, runReview } from "./orchestrate.ts";
import { transposeReport } from "./transpose.ts";

const PRIVATE_FILE_MODE = 0o600;

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function isSubagent(): boolean {
	const depth = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0");
	return Number.isFinite(depth) && depth > 0;
}

async function resolveDefaultBase(pi: ExtensionAPI, cwd: string): Promise<string> {
	const head = await exec(pi, "git", ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], { cwd });
	const ref = head.stdout.trim();
	return ref.startsWith("origin/") ? ref.slice("origin/".length) : "main";
}

async function resolveCurrentBranch(pi: ExtensionAPI, cwd: string): Promise<string> {
	const branch = await exec(pi, "git", ["branch", "--show-current"], { cwd });
	return branch.stdout.trim() || "HEAD";
}

function resolveModelReference(ctx: ExtensionCommandContext, modelReference: string): Model<any> | undefined {
	const separator = modelReference.indexOf("/");
	if (separator > 0 && separator < modelReference.length - 1) {
		const provider = modelReference.slice(0, separator);
		const modelId = modelReference.slice(separator + 1);
		return ctx.modelRegistry.find(provider, modelId);
	}

	const matches = ctx.modelRegistry.getAll().filter((model) => model.id === modelReference);
	return matches.length === 1 ? matches[0] : undefined;
}

async function resolveReviewTransposerModel(
	ctx: ExtensionCommandContext,
	deps: Pick<PiSwarmDependencies, "resolveModelAlias">,
): Promise<{ model: Model<any>; auth: { apiKey?: string; headers?: Record<string, string> } } | null> {
	const modelReference = deps.resolveModelAlias("fast");
	if (!modelReference) return null;

	const model = resolveModelReference(ctx, modelReference);
	if (!model) return null;

	try {
		const auth = await ctx.modelRegistry.getApiKeyAndHeaders(model);
		if (!auth.ok || (!auth.apiKey && !(auth.headers && Object.keys(auth.headers).length > 0))) return null;
		return { model, auth: { apiKey: auth.apiKey, headers: auth.headers } };
	} catch {
		return null;
	}
}

function persistReviewArtifact(result: Awaited<ReturnType<typeof runReview>>): string {
	const dir = path.join(process.env.BASECAMP_SCRATCH_DIR || os.tmpdir(), "code-review");
	fs.mkdirSync(dir, { recursive: true });
	const filename = `review-${Date.now()}-${randomBytes(4).toString("hex")}.json`;
	const artifactPath = path.join(dir, filename);
	const fd = fs.openSync(
		artifactPath,
		fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY,
		PRIVATE_FILE_MODE,
	);
	try {
		fs.writeFileSync(fd, `${JSON.stringify(result, null, 2)}\n`, "utf8");
		fs.chmodSync(artifactPath, PRIVATE_FILE_MODE);
	} finally {
		fs.closeSync(fd);
	}
	return artifactPath;
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
				const currentBranch = await resolveCurrentBranch(pi, cwd);
				const diff = await exec(pi, "git", ["diff", "--quiet", `${base}...HEAD`], { cwd });
				if (diff.code === 0) {
					ctx.ui.notify(`No changes to review between ${base} and HEAD.`, "info");
					return;
				}
				if (diff.code !== 1) {
					throw new Error(diff.stderr.trim() || `git diff failed with exit code ${diff.code}`);
				}

				const transposer = await resolveReviewTransposerModel(ctx, deps);
				if (!transposer) {
					ctx.ui.notify("Review transposer model (fast) unavailable; aborting.", "error");
					return;
				}

				const scope = {
					base,
					head: "HEAD",
					cwd,
					label: `branch ${currentBranch} → ${base}`,
				};

				ctx.ui.notify(`Running independent code review — dispatching ${REVIEWERS.length} reviewers…`, "info");

				const orchestrateDeps: OrchestrateDeps = {
					dispatchReviewer: async (spec, brief) => {
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
								process.env.BASECAMP_SESSION_NAME ?? pi.getSessionName()?.trim() ?? ctx.sessionManager.getSessionId(),
							project: process.env.BASECAMP_PROJECT ?? "default",
						});
						if (!launch.ok) throw new Error(launch.message);

						const { plan } = launch;
						const taskSpec = plan.args.at(-1);
						if (!taskSpec) throw new Error("Unable to build async task argument.");

						let agentHandle = buildAgentHandle();
						let dispatchResult: Awaited<ReturnType<typeof daemonClient.dispatchAgent>> | null = null;
						const dispatchEnv = {
							...processEnvForSpawn(),
							...plan.environment,
							BASECAMP_AGENT_TITLE: `(review → ${spec.dimension})`,
						};

						for (let attempt = 0; attempt < 3; attempt++) {
							dispatchResult = await daemonClient.dispatchAgent({
								agentId,
								agentHandle,
								agentType: "review",
								runKind: plan.runKind,
								model: plan.model ?? "default",
								argv: plan.args.slice(0, -1),
								task: taskSpec,
								cwd: plan.spawnCwd,
								env: { ...dispatchEnv, BASECAMP_AGENT_HANDLE: agentHandle },
							});
							if (
								dispatchResult.status !== "rejected" ||
								dispatchResult.reason !== "duplicate_agent_handle" ||
								attempt === 2
							) {
								break;
							}
							agentHandle = buildAgentHandle();
						}

						if (!dispatchResult || dispatchResult.status === "rejected") {
							throw new Error(`dispatch rejected: ${dispatchResult?.reason ?? "unknown"}`);
						}

						return agentHandle;
					},
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

				const result = await runReview(scope, orchestrateDeps);
				const artifactPath = persistReviewArtifact(result);
				pi.sendUserMessage(formatReviewPrompt(result, artifactPath));
				ctx.ui.notify(`Code review complete: ${result.verdict.decision} (${result.findings.length} findings)`, "info");
			} catch (error) {
				ctx.ui.notify(`Code review failed: ${errorMessage(error)}`, "error");
			}
		},
	});
}
