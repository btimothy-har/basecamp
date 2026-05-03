import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { SessionEntry } from "@mariozechner/pi-coding-agent";
import type { WorkspaceState } from "../../platform/workspace.ts";
import { latestWorkspaceAffinity, repoMatchesWorkspaceAffinity, type WorkspaceAffinity } from "../src/affinity.ts";
import { WORKSPACE_AFFINITY_ENTRY } from "../src/constants.ts";

const REPO_ROOT = "/repo";
const REPO_NAME = "repo";
const REMOTE_URL = "git@github.com:test/repo.git";
const WORKTREE_DIR = "/worktrees/repo/feature";

function affinity(overrides: Partial<WorkspaceAffinity> = {}): WorkspaceAffinity {
	return {
		version: 1,
		repoName: REPO_NAME,
		repoRoot: REPO_ROOT,
		remoteUrl: REMOTE_URL,
		executionTarget: {
			kind: "git-worktree",
			label: "feature",
			path: WORKTREE_DIR,
			branch: "bh/feature",
		},
		updatedAt: "2026-05-03T00:00:00.000Z",
		...overrides,
	};
}

function entry(data: unknown, overrides: Record<string, unknown> = {}): SessionEntry {
	return {
		type: "custom",
		customType: WORKSPACE_AFFINITY_ENTRY,
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
		executionTarget: null,
		unsafeEdit: false,
		...overrides,
	};
}

describe("workspace affinity", () => {
	describe("latestWorkspaceAffinity", () => {
		it("returns the latest valid affinity entry when scanning backward", () => {
			const older = affinity({
				executionTarget: { kind: "git-worktree", label: "older", path: "/wt/older", branch: "old" },
			});
			const latest = affinity({
				executionTarget: { kind: "git-worktree", label: "latest", path: "/wt/latest", branch: "new" },
			});

			assert.deepEqual(latestWorkspaceAffinity([entry(older), entry(latest)]), latest);
		});

		it("skips invalid latest affinity entries in favor of earlier valid ones", () => {
			const valid = affinity({
				executionTarget: { kind: "git-worktree", label: "valid", path: "/wt/valid", branch: "valid" },
			});

			assert.deepEqual(
				latestWorkspaceAffinity([
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
				entry({ ...affinity(), executionTarget: { kind: "git-worktree", label: "feature", path: WORKTREE_DIR } }),
				entry(null),
			];

			assert.equal(latestWorkspaceAffinity(entries), null);
		});

		it("accepts null remoteUrl and null branch as valid affinity data", () => {
			const valid = affinity({
				remoteUrl: null,
				executionTarget: { kind: "git-worktree", label: "feature", path: WORKTREE_DIR, branch: null },
			});

			assert.deepEqual(latestWorkspaceAffinity([entry(valid)]), valid);
		});
	});

	describe("repoMatchesWorkspaceAffinity", () => {
		it("returns false when there is no repo", () => {
			assert.equal(repoMatchesWorkspaceAffinity(workspaceState({ repo: null }), affinity()), false);
		});

		it("returns false for repo name or repo root mismatches", () => {
			assert.equal(
				repoMatchesWorkspaceAffinity(
					workspaceState({ repo: { isRepo: true, name: "other", root: REPO_ROOT, remoteUrl: REMOTE_URL } }),
					affinity(),
				),
				false,
			);
			assert.equal(
				repoMatchesWorkspaceAffinity(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: "/other", remoteUrl: REMOTE_URL } }),
					affinity(),
				),
				false,
			);
		});

		it("normalizes equivalent repo root paths", () => {
			assert.equal(
				repoMatchesWorkspaceAffinity(
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
				repoMatchesWorkspaceAffinity(
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
				repoMatchesWorkspaceAffinity(
					workspaceState({ repo: { isRepo: true, name: REPO_NAME, root: REPO_ROOT, remoteUrl: null } }),
					affinity(),
				),
				true,
			);
			assert.equal(repoMatchesWorkspaceAffinity(workspaceState(), affinity({ remoteUrl: null })), true);
		});
	});
});
