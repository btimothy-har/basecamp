import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorktreeResult } from "#core/git/worktrees/crud.ts";
import { shouldRunWorktreeSetup, type WorktreeSetupResult } from "#core/project/workspace/setup.ts";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import {
	errorMessage,
	type WorkstreamToolsDeps,
	workstreamLaunchCommand,
	workstreamLaunchCommandFromPath,
} from "./deps.ts";
import type { HerdrWorkstreamOpenResult } from "./herdr.ts";
import type { LaunchWorkstreamResultDetails } from "./results.ts";

export function workspaceForHerdr(workspace: WorkspaceState | null, hasUI: boolean) {
	return {
		...(workspace?.protectedRoot ? { protectedRoot: workspace.protectedRoot } : {}),
		...(workspace?.repo?.root ? { repo: { root: workspace.repo.root } } : {}),
		...(workspace?.launchCwd ? { launchCwd: workspace.launchCwd } : {}),
		hasUI,
	};
}

export function resultWorktree(worktree: WorktreeResult): LaunchWorkstreamResultDetails["worktree"] {
	return {
		label: worktree.label,
		path: worktree.worktreeDir,
		branch: worktree.branch,
		created: worktree.created,
	};
}

export async function provisionWorktree(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	repoRoot: string,
	repo: string,
	worktreeLabel: string,
	branchName: string | null,
): Promise<{ worktree: WorktreeResult; error?: string; stagingError?: string }> {
	let worktree: WorktreeResult;
	try {
		worktree = await deps.getOrCreateWorktree(pi, repoRoot, repo, worktreeLabel, branchName);
	} catch (err) {
		return {
			worktree: { worktreeDir: "", label: worktreeLabel, branch: branchName ?? "", created: false },
			error: errorMessage(err),
		};
	}
	// The staged lock is what keeps the cold session-start sweep from reaping this worktree
	// before `pi --workstream` launches in it; without it the tree reads as leaseless residue.
	// A staging failure is NOT fatal to provisioning: aborting here would strand a created
	// worktree whose retry skips the setup hook (the reuse path reports created: false), so the
	// launch continues and the failure rides along as stagingError for the caller to surface.
	try {
		await deps.stageWorktreeLock(pi, repoRoot, worktree.worktreeDir);
		return { worktree };
	} catch (err) {
		return { worktree, stagingError: errorMessage(err) };
	}
}

export async function runSetup(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	repoRoot: string,
	repo: string,
	worktree: WorktreeResult,
): Promise<WorktreeSetupResult | { status: string; message: string }> {
	const setupCommand = deps.readWorktreeSetupCommand(repo);
	if (!shouldRunWorktreeSetup(worktree.created, setupCommand)) {
		return {
			status: "skipped",
			message: setupCommand
				? "Worktree setup skipped because the worktree was not newly created."
				: "Worktree setup skipped because no setup command is configured.",
		};
	}
	try {
		return await deps.runWorktreeSetup(pi, {
			command: setupCommand as string,
			worktreeDir: worktree.worktreeDir,
			repoRoot,
		});
	} catch (err) {
		return { status: "failed", message: `Worktree setup threw an error; continuing. (${errorMessage(err)})` };
	}
}

export async function openHerdr(
	deps: WorkstreamToolsDeps,
	pi: ExtensionAPI,
	workspace: WorkspaceState | null,
	ctx: ExtensionContext,
	worktree: WorktreeResult,
): Promise<HerdrWorkstreamOpenResult> {
	return await deps.openWorkstreamInHerdr(
		pi,
		workspaceForHerdr(workspace, ctx.hasUI),
		{ path: worktree.worktreeDir, label: worktree.label },
		process.env,
	);
}

export function herdrToSummary(herdr: HerdrWorkstreamOpenResult): unknown {
	return herdr;
}

export function buildNextStep(herdr: HerdrWorkstreamOpenResult, worktree: WorktreeResult, slug: string): string {
	const pathCommand = workstreamLaunchCommandFromPath(worktree.worktreeDir, slug);
	if (herdr.status === "opened") {
		return `Herdr opened a pane for worktree ${worktree.label}. In that pane, run \`${workstreamLaunchCommand(slug)}\`.`;
	}
	if (herdr.status === "skipped") {
		return `Worktree ${worktree.label} is ready, but no Herdr pane was opened (${herdr.message}). Run \`${pathCommand}\`.`;
	}
	return `Worktree ${worktree.label} is ready, but the Herdr pane failed to open (${herdr.message}). Run \`${pathCommand}\`.`;
}
