import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { copilotWorktreeTarget } from "#core/git/worktrees/target.ts";
import type { WorkstreamDetail } from "../../agents/client.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "../deps.ts";
import { type LaunchWorkstreamParams, parseLaunchWorkstreamParams } from "../params.ts";
import { buildNextStep, herdrToSummary, openHerdr, provisionWorktree, resultWorktree, runSetup } from "../provision.ts";
import { failedLaunchDetails, type LaunchWorkstreamToolResult, textResult } from "../results.ts";
import { executeCreateWorkstream } from "./create.ts";

async function executeCarryWorkstream(
	parsed: LaunchWorkstreamParams,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	deps: WorkstreamToolsDeps,
): Promise<LaunchWorkstreamToolResult> {
	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo || !workspace.repo.root) {
		return textResult(
			failedLaunchDetails(
				"launch_workstream requires a current git repository workspace.",
				"Open a repository-backed Basecamp workspace, then call launch_workstream again.",
			),
			true,
		);
	}

	const repo = workspace.repo.name;
	const repoRoot = workspace.repo.root;
	const socketPath = deps.resolveSocketPath();
	const identifier = parsed.workstreamId as string;

	let detail: WorkstreamDetail | null;
	try {
		detail = await deps.getWorkstreamDetail(socketPath, identifier);
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not resolve workstream "${identifier}": ${errorMessage(err)}`,
				"Check the workstream id or slug with list_workstreams, then call launch_workstream again.",
			),
			true,
		);
	}
	if (!detail?.slug) {
		return textResult(
			failedLaunchDetails(
				`No workstream found for "${identifier}".`,
				"Use list_workstreams to find an existing workstream id or slug, then pass it as the workstream parameter.",
			),
			true,
		);
	}

	const slug = detail.slug;
	const worktreeTarget = copilotWorktreeTarget(parsed.workstream.worktreeSlug ?? parsed.workstream.label, slug);

	// getOrCreateWorktree is idempotent — reuses if present
	const { worktree, error: provisionError } = await provisionWorktree(
		deps,
		pi,
		repoRoot,
		repo,
		worktreeTarget.worktreeLabel,
		worktreeTarget.branchName,
	);
	if (provisionError) {
		return textResult(
			failedLaunchDetails(
				`Failed to provision worktree ${worktreeTarget.worktreeLabel}: ${provisionError}`,
				"Fix worktree provisioning, then retry launch_workstream with the same workstream identifier.",
			),
			true,
		);
	}

	const setupSummary = await runSetup(deps, pi, repoRoot, repo, worktree);
	const herdrResult = await openHerdr(deps, pi, workspace, ctx, worktree);
	const nextStep = buildNextStep(herdrResult, worktree, slug);

	return textResult({
		status: "carried",
		message: `Workstream "${detail.label ?? slug}" carried to ${repo}.`,
		id: detail.id ?? undefined,
		slug,
		worktree: resultWorktree(worktree),
		setup_summary: setupSummary,
		herdr_summary: herdrToSummary(herdrResult),
		next_step: nextStep,
	});
}

export async function executeLaunchWorkstream(
	params: unknown,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	_signal?: AbortSignal,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<LaunchWorkstreamToolResult> {
	const parsed = parseLaunchWorkstreamParams(params);
	if (!parsed.ok) {
		return textResult(
			failedLaunchDetails(parsed.message, "Call launch_workstream again with non-empty required fields."),
			true,
		);
	}

	if (parsed.value.workstreamId) {
		return executeCarryWorkstream(parsed.value, pi, ctx, deps);
	}
	return executeCreateWorkstream(parsed.value, pi, ctx, deps);
}
