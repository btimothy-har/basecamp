import * as path from "node:path";
import {
	copilotWorktreeTarget,
	currentUserId,
	type ExecutionWorktreeTarget,
	normalizeWorktreeSlug,
	userWorktreePrefix,
} from "#core/git/worktrees/target.ts";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";

export { copilotWorktreeTarget, type ExecutionWorktreeTarget, userWorktreePrefix };

export const CUSTOM_WORKTREE_CHOICE = "Enter custom worktree label";

const SUGGESTED_WORKTREE_LABEL_MAX_LENGTH = 32;
const FALLBACK_WORKTREE_SLUG = "worktree";

export interface ExecutionWorktreeChoices {
	choices: string[];
	targetsByChoice: Map<string, ExecutionWorktreeTarget>;
}

function normalizeSessionTag(value: string | null | undefined): string {
	return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function stripKnownPrefix(value: string, prefix: string): string {
	const lower = value.trim().toLowerCase();
	for (const knownPrefix of [`wt-${prefix}/`, `wt/`, `${prefix}/`, `wt-${prefix}-`, `${prefix}-`]) {
		if (lower.startsWith(knownPrefix)) return lower.slice(knownPrefix.length);
	}
	return lower;
}

// The worktree directory is a generic `wt/<slug>` cache (issue #310 Phase 3); the branch
// `<prefix>/<tag>-<slug>` carries the unique identity. The slug is capped so the branch (the
// longer, durable identifier) stays bounded; worktree-name collisions are disambiguated at
// provision time via resolveAvailableWorktreeLabel, so the builder stays pure.
function buildExecutionWorktreeTarget(prefix: string, slug: string, sessionTag: string): ExecutionWorktreeTarget {
	const branchPrefix = `${prefix}/`;
	const tag = normalizeSessionTag(sessionTag);
	const tagSegment = tag ? `${tag}-` : "";
	const baseSlug = tagSegment && slug.startsWith(tagSegment) ? slug.slice(tagSegment.length) : slug;
	const maxSlugLength = Math.max(1, SUGGESTED_WORKTREE_LABEL_MAX_LENGTH - branchPrefix.length - tagSegment.length);
	const cappedSlug = baseSlug.slice(0, maxSlugLength).replace(/-+$/g, "") || FALLBACK_WORKTREE_SLUG;
	return {
		worktreeLabel: `wt/${cappedSlug}`,
		branchName: `${branchPrefix}${tagSegment}${cappedSlug}`,
	};
}

function existingWorktreeTarget(wt: WorkspaceWorktree): ExecutionWorktreeTarget {
	return { worktreeLabel: wt.label, branchName: null };
}

export function suggestWorktreeTarget(
	goal: string,
	worktreeSlug: string | null,
	sessionTag: string,
	userId = currentUserId(),
): ExecutionWorktreeTarget {
	const prefix = userWorktreePrefix(userId);
	const slug = normalizeWorktreeSlug(worktreeSlug ?? goal);
	return buildExecutionWorktreeTarget(prefix, slug, sessionTag);
}

export function customWorktreeTarget(
	value: string,
	sessionTag: string,
	userId = currentUserId(),
): ExecutionWorktreeTarget {
	const prefix = userWorktreePrefix(userId);
	const slug = normalizeWorktreeSlug(stripKnownPrefix(value, prefix));
	return buildExecutionWorktreeTarget(prefix, slug, sessionTag);
}

function normalizeWorktreePath(value: string): string {
	const normalized = path.normalize(value);
	const root = path.parse(normalized).root;
	return normalized.length > root.length ? normalized.replace(/[\\/]+$/, "") : normalized;
}

function matchingRegisteredActiveWorktree(
	existing: WorkspaceWorktree[],
	active: WorkspaceWorktree | null,
): WorkspaceWorktree | null {
	if (!active) return null;
	const activePath = normalizeWorktreePath(active.path);
	return existing.find((wt) => wt.label === active.label && normalizeWorktreePath(wt.path) === activePath) ?? null;
}

export function buildExecutionWorktreeChoices(
	suggested: ExecutionWorktreeTarget,
	existing: WorkspaceWorktree[],
	active: WorkspaceWorktree | null,
): ExecutionWorktreeChoices {
	const choices: string[] = [];
	const targetsByChoice = new Map<string, ExecutionWorktreeTarget>();
	const handledLabels = new Set<string>();

	const activeExisting = matchingRegisteredActiveWorktree(existing, active);
	if (activeExisting) {
		const choice = `Current: ${activeExisting.label} (${activeExisting.branch ?? "detached"})`;
		choices.push(choice);
		targetsByChoice.set(choice, existingWorktreeTarget(activeExisting));
		handledLabels.add(activeExisting.label);
	}

	// A generic `wt/<slug>` label no longer uniquely identifies a branch, so when a worktree
	// already holds it we resume THAT worktree (reuse its branch) rather than forcing the
	// suggested branch; only a free label offers a fresh Create on the suggested branch.
	const suggestedExisting = existing.find((wt) => wt.label === suggested.worktreeLabel);
	if (!handledLabels.has(suggested.worktreeLabel)) {
		if (suggestedExisting) {
			const choice = `Resume: ${suggestedExisting.label} (${suggestedExisting.branch ?? "detached"})`;
			choices.push(choice);
			targetsByChoice.set(choice, existingWorktreeTarget(suggestedExisting));
		} else {
			const choice = `Create: ${suggested.worktreeLabel}`;
			choices.push(choice);
			targetsByChoice.set(choice, suggested);
		}
	}
	handledLabels.add(suggested.worktreeLabel);

	for (const wt of existing) {
		if (handledLabels.has(wt.label)) continue;
		const choice = `Resume: ${wt.label} (${wt.branch ?? "detached"})`;
		choices.push(choice);
		targetsByChoice.set(choice, existingWorktreeTarget(wt));
		handledLabels.add(wt.label);
	}
	choices.push(CUSTOM_WORKTREE_CHOICE);
	return { choices, targetsByChoice };
}
