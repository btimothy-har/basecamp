import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { copilotWorktreeTarget } from "#core/git/worktrees/target.ts";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";
import { defaultWorkstreamToolsDeps, errorMessage, type WorkstreamToolsDeps } from "./deps.ts";
import { parseLaunchWorkstreamParams } from "./params.ts";
import { buildNextStep, herdrToSummary, openHerdr, provisionWorktree, resultWorktree, runSetup } from "./provision.ts";
import { resolveWorkstreamDetail } from "./resolve.ts";
import { failedDetails, type LaunchWorkstreamToolResult, toolResult } from "./results.ts";

/**
 * launch_workstream — stage execution for an EXISTING workstream: provision the
 * `copilot/<slug>` worktree (idempotent) and best-effort open a Herdr pane on it.
 * Resolves the workstream by id/slug; it never creates one (use create_workstream first)
 * and does not start an agent. Carries the workstream into whatever repo the session is in.
 */
export async function executeLaunchWorkstream(
	params: unknown,
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	_signal?: AbortSignal,
	deps: WorkstreamToolsDeps = defaultWorkstreamToolsDeps(async () => null),
): Promise<LaunchWorkstreamToolResult> {
	const parsed = parseLaunchWorkstreamParams(params);
	if (!parsed.ok) {
		return toolResult(
			failedDetails(parsed.message, "Call launch_workstream again with a workstream id or slug."),
			true,
		);
	}

	const workspace = deps.getWorkspaceState();
	if (!workspace?.repo?.isRepo || !workspace.repo.root) {
		return toolResult(
			failedDetails(
				"launch_workstream requires a current git repository workspace.",
				"Open a repository-backed Basecamp workspace, then call launch_workstream again.",
			),
			true,
		);
	}

	const repo = workspace.repo.name;
	const repoRoot = workspace.repo.root;
	const identifier = parsed.value.workstream;

	const resolved = await resolveWorkstreamDetail(deps, identifier);
	if (!resolved.ok) {
		return resolved.reason === "error"
			? toolResult(
					failedDetails(
						`Could not resolve workstream "${identifier}": ${resolved.message}`,
						"Check the workstream id or slug with list_workstreams, then call launch_workstream again.",
					),
					true,
				)
			: toolResult(
					failedDetails(
						resolved.message,
						"Create it first with create_workstream, then call launch_workstream with its id or slug.",
					),
					true,
				);
	}
	const detail = resolved.detail;
	const slug = detail.slug;
	const worktreeTarget = copilotWorktreeTarget(parsed.value.worktreeSlug ?? detail.label ?? slug, slug);

	// Guard against a derived branch already checked out in another worktree for this repo.
	let existingWorktrees: WorkspaceWorktree[];
	try {
		existingWorktrees = await deps.listWorkspaceWorktrees();
	} catch (err) {
		return toolResult(
			failedDetails(
				`Could not list existing worktrees: ${errorMessage(err)}`,
				"Fix worktree listing for this repository, then call launch_workstream again.",
			),
			true,
		);
	}
	if (worktreeTarget.branchName && existingWorktrees.some((wt) => wt.branch === worktreeTarget.branchName)) {
		return toolResult(
			failedDetails(
				`The branch ${worktreeTarget.branchName} is already checked out in another worktree for this repo.`,
				"Call launch_workstream again with a distinct worktreeSlug so the initial branch name is not already checked out.",
			),
			true,
		);
	}

	// getOrCreateWorktree is idempotent — reuses if present.
	const { worktree, error: provisionError } = await provisionWorktree(
		deps,
		pi,
		repoRoot,
		repo,
		worktreeTarget.worktreeLabel,
		worktreeTarget.branchName,
	);
	if (provisionError) {
		return toolResult(
			failedDetails(
				`Failed to provision worktree ${worktreeTarget.worktreeLabel}: ${provisionError}`,
				"Fix worktree provisioning, then retry launch_workstream with the same workstream identifier.",
			),
			true,
		);
	}

	const setupSummary = await runSetup(deps, pi, repoRoot, repo, worktree);
	const herdrResult = await openHerdr(deps, pi, workspace, ctx, worktree);
	const nextStep = buildNextStep(herdrResult, worktree, slug);

	return toolResult({
		status: "launched",
		message: `Workstream "${detail.label ?? slug}" launched in ${repo}.`,
		id: detail.id ?? undefined,
		slug,
		worktree: resultWorktree(worktree),
		setup_summary: setupSummary,
		herdr_summary: herdrToSummary(herdrResult),
		next_step: nextStep,
	});
}
