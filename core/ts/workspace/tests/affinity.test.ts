import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { WorkspaceState, WorkspaceWorktree } from "../../platform/workspace.ts";
import type { SessionStateActiveWorktree } from "../../state/index.ts";
import { buildActiveWorktreeState, workspaceMatchesActiveWorktreeState } from "../affinity.ts";

const REPO_ROOT = "/repo";
const REPO_NAME = "repo";
const REMOTE_URL = "git@github.com:test/repo.git";
const WORKTREE_DIR = "/worktrees/repo/feature";

function worktree(overrides: Partial<WorkspaceWorktree> = {}): WorkspaceWorktree {
	return {
		kind: "git-worktree",
		label: "feature",
		path: WORKTREE_DIR,
		branch: "bh/feature",
		created: false,
		...overrides,
	};
}

function activeWorktree(overrides: Partial<SessionStateActiveWorktree> = {}): SessionStateActiveWorktree {
	return {
		version: 1,
		repoName: REPO_NAME,
		repoRoot: REPO_ROOT,
		remoteUrl: REMOTE_URL,
		worktree: worktree(),
		updatedAt: "2026-05-03T00:00:00.000Z",
		...overrides,
	};
}

function workspaceState(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: REPO_ROOT,
		effectiveCwd: REPO_ROOT,
		scratchDir: "/tmp/pi/repo",
		repo: {
			isRepo: true,
			name: REPO_NAME,
			root: REPO_ROOT,
			remoteUrl: REMOTE_URL,
		},
		protectedRoot: REPO_ROOT,
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	};
}

describe("workspace state-backed affinity", () => {
	describe("buildActiveWorktreeState", () => {
		it("builds persisted active worktree metadata from workspace state and worktree", () => {
			const target = worktree({ branch: null, created: true });
			const built = buildActiveWorktreeState(workspaceState(), target);

			assert.deepEqual(built, {
				version: 1,
				repoName: REPO_NAME,
				repoRoot: REPO_ROOT,
				remoteUrl: REMOTE_URL,
				worktree: target,
				updatedAt: built?.updatedAt,
			});
			assert.match(built?.updatedAt ?? "", /^\d{4}-\d{2}-\d{2}T/);
			assert.notEqual(built?.worktree, target);
		});

		it("returns null when there is no repo", () => {
			assert.equal(buildActiveWorktreeState(workspaceState({ repo: null }), worktree()), null);
		});
	});

	describe("workspaceMatchesActiveWorktreeState", () => {
		it("returns false when there is no repo", () => {
			assert.equal(workspaceMatchesActiveWorktreeState(workspaceState({ repo: null }), activeWorktree()), false);
		});

		it("returns false for repo name or repo root mismatches", () => {
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({ repo: { isRepo: true, name: "other", root: REPO_ROOT, remoteUrl: REMOTE_URL } }),
					activeWorktree(),
				),
				false,
			);
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: "/other", remoteUrl: REMOTE_URL } }),
					activeWorktree(),
				),
				false,
			);
		});

		it("normalizes equivalent repo root paths", () => {
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({
						repo: { isRepo: true, name: REPO_NAME, root: `${REPO_ROOT}${path.sep}`, remoteUrl: REMOTE_URL },
					}),
					activeWorktree(),
				),
				true,
			);
		});

		it("distinguishes slashed identities with the same basename", () => {
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({ repo: { isRepo: true, name: "orgB/repo", root: REPO_ROOT, remoteUrl: null } }),
					activeWorktree({ repoName: "orgA/repo", remoteUrl: null }),
				),
				false,
			);
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({ repo: { isRepo: true, name: "orgA/repo", root: REPO_ROOT, remoteUrl: null } }),
					activeWorktree({ repoName: "orgA/repo", remoteUrl: null }),
				),
				true,
			);
		});

		it("only fails remote URL mismatches when both remotes are non-null and different", () => {
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({
						repo: {
							isRepo: true,
							name: REPO_NAME,
							root: REPO_ROOT,
							remoteUrl: "git@github.com:test/other.git",
						},
					}),
					activeWorktree(),
				),
				false,
			);
			assert.equal(
				workspaceMatchesActiveWorktreeState(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: REPO_ROOT, remoteUrl: null } }),
					activeWorktree(),
				),
				true,
			);
			assert.equal(workspaceMatchesActiveWorktreeState(workspaceState(), activeWorktree({ remoteUrl: null })), true);
		});
	});
});
