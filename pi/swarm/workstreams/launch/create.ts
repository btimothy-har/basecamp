import { randomUUID } from "node:crypto";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { copilotWorktreeTarget } from "#core/git/worktrees/target.ts";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";
import type { DaemonClient } from "../../agents/client.ts";
import { errorMessage, type WorkstreamToolsDeps } from "../deps.ts";
import type { LaunchWorkstreamParams } from "../params.ts";
import { buildNextStep, herdrToSummary, openHerdr, provisionWorktree, resultWorktree, runSetup } from "../provision.ts";
import { failedLaunchDetails, type LaunchWorkstreamToolResult, textResult } from "../results.ts";

export async function executeCreateWorkstream(
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

	const client = await deps.getClient();
	if (!client) {
		return textResult(
			failedLaunchDetails(
				"basecamp hub is not connected; cannot create a workstream.",
				"Ensure the daemon is running (it starts automatically for top-level sessions), then call launch_workstream again.",
			),
			true,
		);
	}

	const workName = parsed.workstream.worktreeSlug ?? parsed.workstream.label;
	const maxSlugAttempts = 25;

	let slug: string | null = null;
	let worktreeTarget: ReturnType<typeof copilotWorktreeTarget> | null = null;

	try {
		for (let attempt = 0; attempt < maxSlugAttempts; attempt += 1) {
			const candidate = deps.generateWorkstreamName(() => false);
			const existing = await deps.getWorkstreamDetail(socketPath, candidate);
			if (existing) continue;
			slug = candidate;
			worktreeTarget = copilotWorktreeTarget(workName, candidate);
			break;
		}
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not generate a unique workstream slug: ${errorMessage(err)}`,
				"Call launch_workstream again; if collisions continue, inspect existing workstreams.",
			),
			true,
		);
	}

	if (!slug || !worktreeTarget) {
		return textResult(
			failedLaunchDetails(
				`Could not generate a unique workstream slug after ${maxSlugAttempts} attempts.`,
				"Call launch_workstream again; if collisions continue, inspect existing workstreams.",
			),
			true,
		);
	}

	// Check the derived bt/ branch isn't already checked out
	let existingWorktrees: WorkspaceWorktree[];
	try {
		existingWorktrees = await deps.listWorkspaceWorktrees();
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Could not list existing worktrees: ${errorMessage(err)}`,
				"Fix worktree listing for this repository, then call launch_workstream again.",
			),
			true,
		);
	}
	if (worktreeTarget.branchName && existingWorktrees.some((wt) => wt.branch === worktreeTarget.branchName)) {
		return textResult(
			failedLaunchDetails(
				`The branch ${worktreeTarget.branchName} is already checked out in another worktree for this repo.`,
				"Call launch_workstream again with a distinct workstream.worktreeSlug so the initial branch name is not already checked out.",
			),
			true,
		);
	}

	// Provision the worktree
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
				"Fix worktree provisioning or choose a different workstream.worktreeSlug, then retry.",
			),
			true,
		);
	}

	// Run setup (transient — not persisted)
	const setupSummary = await runSetup(deps, pi, repoRoot, repo, worktree);

	// Open Herdr (transient — not persisted)
	const herdrResult = await openHerdr(deps, pi, workspace, ctx, worktree);

	// Create the workstream in the daemon
	const workstreamId = `ws_${randomUUID()}`;
	let createResult: Awaited<ReturnType<DaemonClient["createWorkstream"]>>;
	try {
		createResult = await client.createWorkstream({
			workstreamId,
			slug,
			label: parsed.workstream.label,
			brief: parsed.workstream.brief,
			sourceDossierPath: parsed.source.dossierPath,
			...(parsed.workstream.constraints ? { constraints: parsed.workstream.constraints } : {}),
			...(parsed.source.repoPagePath ? { sourceRepoPagePath: parsed.source.repoPagePath } : {}),
		});
	} catch (err) {
		return textResult(
			failedLaunchDetails(
				`Failed to create workstream in daemon: ${errorMessage(err)}`,
				"The worktree is provisioned; retry launch_workstream (the slug will be regenerated).",
			),
			true,
		);
	}

	// On slug_conflict, regenerate and retry the create (worktree is reusable if label matches)
	if (createResult.status === "slug_conflict") {
		for (let retry = 0; retry < maxSlugAttempts; retry += 1) {
			const retrySlug = deps.generateWorkstreamName(() => false);
			const retryExisting = await deps.getWorkstreamDetail(socketPath, retrySlug);
			if (retryExisting) continue;
			try {
				createResult = await client.createWorkstream({
					workstreamId,
					slug: retrySlug,
					label: parsed.workstream.label,
					brief: parsed.workstream.brief,
					sourceDossierPath: parsed.source.dossierPath,
					...(parsed.workstream.constraints ? { constraints: parsed.workstream.constraints } : {}),
					...(parsed.source.repoPagePath ? { sourceRepoPagePath: parsed.source.repoPagePath } : {}),
				});
			} catch (err) {
				return textResult(
					failedLaunchDetails(
						`Failed to create workstream in daemon: ${errorMessage(err)}`,
						"The worktree is provisioned; retry launch_workstream.",
					),
					true,
				);
			}
			if (createResult.status === "created") {
				slug = retrySlug;
				break;
			}
			if (createResult.status === "slug_conflict") continue;
			break;
		}
	}

	if (createResult.status !== "created") {
		return textResult(
			failedLaunchDetails(
				`Daemon rejected workstream creation: ${createResult.error ?? createResult.status}`,
				"The worktree is provisioned; inspect the daemon error and retry launch_workstream.",
			),
			true,
		);
	}

	const nextStep = buildNextStep(herdrResult, worktree, slug);

	return textResult({
		status: "launched",
		message: `Workstream "${parsed.workstream.label}" created as ${slug}.`,
		id: createResult.workstream_id ?? workstreamId,
		slug,
		worktree: resultWorktree(worktree),
		setup_summary: setupSummary,
		herdr_summary: herdrToSummary(herdrResult),
		next_step: nextStep,
	});
}
