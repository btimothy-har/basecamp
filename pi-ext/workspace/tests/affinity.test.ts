import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { SessionEntry } from "@mariozechner/pi-coding-agent";
import {
	latestWorkspaceWorktreeAffinity,
	workspaceMatchesWorktreeAffinity,
	WORKTREE_AFFINITY_ENTRY,
	type WorkspaceState,
	type WorkspaceWorktreeAffinity,
} from "../../platform/workspace.ts";

const REPO_ROOT = "/repo";
const REPO_NAME = "repo";
const REMOTE_URL = "git@github.com:test/repo.git";
const WORKTREE_DIR = "/worktrees/repo/feature";

function affinity(overrides: Partial<WorkspaceWorktreeAffinity> = {}): WorkspaceWorktreeAffinity {
	return {
		version: 1,
		repoName: REPO_NAME,
		repoRoot: REPO_ROOT,
		remoteUrl: REMOTE_URL,
		worktree: {
			kind: "git-worktree",
			label: "feature",
			path: WORKTREE_DIR,
			branch: "bh/feature",
			created: false,
		},
		updatedAt: "2026-05-03T00:00:00.000Z",
		...overrides,
	};
}

function entry(data: unknown, overrides: Record<string, unknown> = {}): SessionEntry {
	return {
		type: "custom",
		customType: WORKTREE_AFFINITY_ENTRY,
		data,
		...overrides,
	} as unknown as SessionEntry;
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

describe("workspace affinity", () => {
	describe("latestWorkspaceWorktreeAffinity", () => {
		it("returns the latest valid affinity entry when scanning backward", () => {
			const older = affinity({
				worktree: { kind: "git-worktree", label: "older", path: "/wt/older", branch: "old", created: false },
			});
			const latest = affinity({
				worktree: { kind: "git-worktree", label: "latest", path: "/wt/latest", branch: "new", created: false },
			});

			assert.deepEqual(latestWorkspaceWorktreeAffinity([entry(older), entry(latest)]), latest);
		});

		it("skips invalid latest affinity entries in favor of earlier valid ones", () => {
			const valid = affinity({
				worktree: { kind: "git-worktree", label: "valid", path: "/wt/valid", branch: "valid", created: false },
			});

			assert.deepEqual(
				latestWorkspaceWorktreeAffinity([
					entry(valid),
					entry({ ...affinity(), version: 2 }),
					entry({ ...affinity(), repoName: 42 }),
				]),
				valid,
			);
		});

		it("ignores entries with wrong customType, wrong type, wrong version, or malformed data", () => {
			const entries = [
				entry(affinity(), { customType: "other.custom-entry" }),
				entry(affinity(), { type: "message" }),
				entry({ ...affinity(), version: 2 }),
				entry({ ...affinity(), worktree: { kind: "git-worktree", label: "feature", path: WORKTREE_DIR } }),
				entry(null),
			];

			assert.equal(latestWorkspaceWorktreeAffinity(entries), null);
		});

		it("accepts null remoteUrl and null branch as valid affinity data", () => {
			const valid = affinity({
				remoteUrl: null,
				worktree: { kind: "git-worktree", label: "feature", path: WORKTREE_DIR, branch: null, created: false },
			});

			assert.deepEqual(latestWorkspaceWorktreeAffinity([entry(valid)]), valid);
		});
	});

	describe("workspaceMatchesWorktreeAffinity", () => {
		it("returns false when there is no repo", () => {
			assert.equal(workspaceMatchesWorktreeAffinity(workspaceState({ repo: null }), affinity()), false);
		});

		it("returns false for repo name or repo root mismatches", () => {
			assert.equal(
				workspaceMatchesWorktreeAffinity(
					workspaceState({ repo: { isRepo: true, name: "other", root: REPO_ROOT, remoteUrl: REMOTE_URL } }),
					affinity(),
				),
				false,
			);
			assert.equal(
				workspaceMatchesWorktreeAffinity(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: "/other", remoteUrl: REMOTE_URL } }),
					affinity(),
				),
				false,
			);
		});

		it("normalizes equivalent repo root paths", () => {
			assert.equal(
				workspaceMatchesWorktreeAffinity(
					workspaceState({
						repo: { isRepo: true, name: REPO_NAME, root: `${REPO_ROOT}${path.sep}`, remoteUrl: REMOTE_URL },
					}),
					affinity(),
				),
				true,
			);
		});

		it("only fails remote URL mismatches when both remotes are non-null and different", () => {
			assert.equal(
				workspaceMatchesWorktreeAffinity(
					workspaceState({
						repo: {
							isRepo: true,
							name: REPO_NAME,
							root: REPO_ROOT,
							remoteUrl: "git@github.com:test/other.git",
						},
					}),
					affinity(),
				),
				false,
			);
			assert.equal(
				workspaceMatchesWorktreeAffinity(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: REPO_ROOT, remoteUrl: null } }),
					affinity(),
				),
				true,
			);
			assert.equal(workspaceMatchesWorktreeAffinity(workspaceState(), affinity({ remoteUrl: null })), true);
		});
	});
});
