/**
 * Pi session affinity for the active workspace worktree.
 *
 * This is session state, not worktree metadata. Git remains the source of
 * truth for whether a worktree exists and belongs to the repo.
 */

import * as path from "node:path";
import type { CustomEntry, ExtensionAPI, SessionEntry } from "@mariozechner/pi-coding-agent";
import type { WorkspaceWorktree, WorkspaceState } from "../../platform/workspace";
import { WORKSPACE_AFFINITY_ENTRY } from "./constants.ts";

export interface WorkspaceAffinity {
	version: 1;
	repoName: string;
	repoRoot: string;
	remoteUrl: string | null;
	executionTarget: {
		kind: string;
		label: string;
		path: string;
		branch: string | null;
	};
	updatedAt: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isWorkspaceWorktreeAffinity(value: unknown): value is WorkspaceAffinity["executionTarget"] {
	return (
		isRecord(value) &&
		typeof value.kind === "string" &&
		typeof value.label === "string" &&
		typeof value.path === "string" &&
		(typeof value.branch === "string" || value.branch === null)
	);
}

function isWorkspaceAffinity(value: unknown): value is WorkspaceAffinity {
	return (
		isRecord(value) &&
		value.version === 1 &&
		typeof value.repoName === "string" &&
		typeof value.repoRoot === "string" &&
		(typeof value.remoteUrl === "string" || value.remoteUrl === null) &&
		isWorkspaceWorktreeAffinity(value.executionTarget) &&
		typeof value.updatedAt === "string"
	);
}

function isAffinityEntry(entry: SessionEntry): entry is CustomEntry<unknown> {
	return entry.type === "custom" && entry.customType === WORKSPACE_AFFINITY_ENTRY;
}

export function latestWorkspaceAffinity(entries: SessionEntry[]): WorkspaceAffinity | null {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i]!;
		if (isAffinityEntry(entry) && isWorkspaceAffinity(entry.data)) return entry.data;
	}
	return null;
}

export function repoMatchesWorkspaceAffinity(state: WorkspaceState, affinity: WorkspaceAffinity): boolean {
	if (!state.repo) return false;
	if (state.repo.name !== affinity.repoName) return false;
	if (path.resolve(state.repo.root) !== path.resolve(affinity.repoRoot)) return false;
	if (state.repo.remoteUrl && affinity.remoteUrl && state.repo.remoteUrl !== affinity.remoteUrl) return false;
	return true;
}

export function appendWorkspaceAffinity(pi: ExtensionAPI, state: WorkspaceState, target: WorkspaceWorktree): void {
	if (!state.repo) return;

	pi.appendEntry(WORKSPACE_AFFINITY_ENTRY, {
		version: 1,
		repoName: state.repo.name,
		repoRoot: state.repo.root,
		remoteUrl: state.repo.remoteUrl,
		executionTarget: {
			kind: target.kind,
			label: target.label,
			path: target.path,
			branch: target.branch,
		},
		updatedAt: new Date().toISOString(),
	} satisfies WorkspaceAffinity);
}
