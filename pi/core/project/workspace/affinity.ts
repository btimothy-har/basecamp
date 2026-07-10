import * as path from "node:path";
import type { SessionStateActiveWorktree } from "../../session/state/index.ts";
import type { WorkspaceState, WorkspaceWorktree } from "./state.ts";

export function buildActiveWorktreeState(
	state: WorkspaceState,
	worktree: WorkspaceWorktree,
): SessionStateActiveWorktree | null {
	if (!state.repo) return null;

	return {
		version: 1,
		repoName: state.repo.name,
		repoRoot: state.repo.root,
		remoteUrl: state.repo.remoteUrl,
		worktree: { ...worktree },
		updatedAt: new Date().toISOString(),
	};
}

export function workspaceMatchesActiveWorktreeState(
	state: WorkspaceState,
	activeWorktree: SessionStateActiveWorktree,
): boolean {
	if (!state.repo) return false;
	if (state.repo.name !== activeWorktree.repoName) return false;
	if (path.resolve(state.repo.root) !== path.resolve(activeWorktree.repoRoot)) return false;
	if (state.repo.remoteUrl && activeWorktree.remoteUrl && state.repo.remoteUrl !== activeWorktree.remoteUrl)
		return false;
	return true;
}
