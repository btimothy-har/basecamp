import * as path from "node:path";
import type { WorkspaceWorktree } from "pi-core/platform/workspace.ts";

export const CUSTOM_WORKTREE_CHOICE = "Enter custom worktree label";

export interface ExecutionWorktreeChoices {
	choices: string[];
	labelsByChoice: Map<string, string>;
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
	suggested: string,
	existing: WorkspaceWorktree[],
	active: WorkspaceWorktree | null,
): ExecutionWorktreeChoices {
	const choices: string[] = [];
	const labelsByChoice = new Map<string, string>();
	const handledLabels = new Set<string>();

	const activeExisting = matchingRegisteredActiveWorktree(existing, active);
	if (activeExisting) {
		const choice = `Current: ${activeExisting.label} (${activeExisting.branch ?? "detached"})`;
		choices.push(choice);
		labelsByChoice.set(choice, activeExisting.label);
		handledLabels.add(activeExisting.label);
	}

	const suggestedExisting = existing.find((wt) => wt.label === suggested);
	if (!handledLabels.has(suggested)) {
		const suggestedChoice = suggestedExisting
			? `Resume: ${suggested} (${suggestedExisting.branch ?? "detached"})`
			: `Create: ${suggested}`;
		choices.push(suggestedChoice);
		labelsByChoice.set(suggestedChoice, suggested);
	}
	handledLabels.add(suggested);

	for (const wt of existing) {
		if (handledLabels.has(wt.label)) continue;
		const choice = `Resume: ${wt.label} (${wt.branch ?? "detached"})`;
		choices.push(choice);
		labelsByChoice.set(choice, wt.label);
		handledLabels.add(wt.label);
	}
	choices.push(CUSTOM_WORKTREE_CHOICE);

	return { choices, labelsByChoice };
}
