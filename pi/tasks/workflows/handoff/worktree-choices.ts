import * as path from "node:path";
import {
	copilotWorktreeTarget,
	currentUserId,
	type ExecutionWorktreeTarget,
	executionWorktreeTarget,
	userWorktreePrefix,
} from "#core/git/worktrees/target.ts";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";

export { copilotWorktreeTarget, type ExecutionWorktreeTarget, userWorktreePrefix };

export const CUSTOM_WORKTREE_CHOICE = "Enter custom worktree label";

export interface ExecutionWorktreeChoices {
	choices: string[];
	targetsByChoice: Map<string, ExecutionWorktreeTarget>;
}

function stripKnownPrefix(value: string, prefix: string): string {
	const lower = value.trim().toLowerCase();
	for (const knownPrefix of [`wt-${prefix}/`, `wt/`, `${prefix}/`, `wt-${prefix}-`, `${prefix}-`]) {
		if (lower.startsWith(knownPrefix)) return lower.slice(knownPrefix.length);
	}
	return lower;
}

/**
 * Target that adopts an existing worktree. It names the branch the picker displayed rather than
 * leaving it null: provisioning ignores the branch when the worktree is still registered, so this
 * only matters if the worktree is reaped between building the choices and the user confirming — and
 * then it rebuilds the branch the user asked for instead of deriving a bogus one from the label.
 */
function existingWorktreeTarget(wt: WorkspaceWorktree): ExecutionWorktreeTarget {
	return { worktreeLabel: wt.label, branchName: wt.branch };
}

export function suggestWorktreeTarget(
	goal: string,
	worktreeSlug: string | null,
	sessionTag: string,
	userId = currentUserId(),
): ExecutionWorktreeTarget {
	return executionWorktreeTarget(worktreeSlug ?? goal, sessionTag, userId);
}

export function customWorktreeTarget(
	value: string,
	sessionTag: string,
	userId = currentUserId(),
): ExecutionWorktreeTarget {
	return executionWorktreeTarget(stripKnownPrefix(value, userWorktreePrefix(userId)), sessionTag, userId);
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
