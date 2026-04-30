/**
 * Pi session affinity for the active Basecamp worktree.
 *
 * This is session state, not worktree metadata. Git remains the source of
 * truth for whether a worktree exists and belongs to the repo.
 */

import * as path from "node:path";
import type { CustomEntry, ExtensionAPI, SessionEntry } from "@mariozechner/pi-coding-agent";
import type { SessionState } from "../../../platform/config";
import type { WorktreeResult } from "./worktree";

const WORKTREE_AFFINITY_ENTRY = "basecamp.worktree-affinity";

export interface WorktreeAffinity {
	version: 2;
	repoName: string;
	repoRoot: string;
	remoteUrl: string | null;
	worktreeLabel: string;
	worktreeDir: string;
	worktreeBranch: string;
	updatedAt: string;
}

interface LegacyWorktreeAffinity {
	version: 1;
	repoName: string;
	primaryDir: string;
	remoteUrl: string | null;
	worktreeLabel: string;
	worktreeDir: string;
	worktreeBranch: string;
	updatedAt: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isAffinityFields(value: Record<string, unknown>): boolean {
	return (
		typeof value.repoName === "string" &&
		(typeof value.remoteUrl === "string" || value.remoteUrl === null) &&
		typeof value.worktreeLabel === "string" &&
		typeof value.worktreeDir === "string" &&
		typeof value.worktreeBranch === "string" &&
		typeof value.updatedAt === "string"
	);
}

function isCurrentAffinity(value: unknown): value is WorktreeAffinity {
	return isRecord(value) && value.version === 2 && typeof value.repoRoot === "string" && isAffinityFields(value);
}

function isLegacyAffinity(value: unknown): value is LegacyWorktreeAffinity {
	return isRecord(value) && value.version === 1 && typeof value.primaryDir === "string" && isAffinityFields(value);
}

function normalizeAffinity(value: unknown): WorktreeAffinity | null {
	if (isCurrentAffinity(value)) return value;
	if (!isLegacyAffinity(value)) return null;
	return {
		version: 2,
		repoName: value.repoName,
		repoRoot: value.primaryDir,
		remoteUrl: value.remoteUrl,
		worktreeLabel: value.worktreeLabel,
		worktreeDir: value.worktreeDir,
		worktreeBranch: value.worktreeBranch,
		updatedAt: value.updatedAt,
	};
}

function isAffinityEntry(entry: SessionEntry): entry is CustomEntry<unknown> {
	return entry.type === "custom" && entry.customType === WORKTREE_AFFINITY_ENTRY;
}

export function latestWorktreeAffinity(entries: SessionEntry[]): WorktreeAffinity | null {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i]!;
		if (isAffinityEntry(entry)) {
			const affinity = normalizeAffinity(entry.data);
			if (affinity) return affinity;
		}
	}
	return null;
}

export function repoMatchesAffinity(state: SessionState, affinity: WorktreeAffinity): boolean {
	if (state.repoName !== affinity.repoName) return false;
	if (path.resolve(state.repoRoot) !== path.resolve(affinity.repoRoot)) return false;
	if (state.remoteUrl && affinity.remoteUrl && state.remoteUrl !== affinity.remoteUrl) return false;
	return true;
}

export function appendWorktreeAffinity(pi: ExtensionAPI, state: SessionState, wt: WorktreeResult): void {
	pi.appendEntry(WORKTREE_AFFINITY_ENTRY, {
		version: 2,
		repoName: state.repoName,
		repoRoot: state.repoRoot,
		remoteUrl: state.remoteUrl,
		worktreeLabel: wt.label,
		worktreeDir: wt.worktreeDir,
		worktreeBranch: wt.branch,
		updatedAt: new Date().toISOString(),
	} satisfies WorktreeAffinity);
}
