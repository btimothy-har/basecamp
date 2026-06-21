import * as os from "node:os";
import * as path from "node:path";
import type { WorkspaceWorktree } from "pi-core/platform/workspace.ts";

export interface ExecutionWorktreeChoices {
	choices: string[];
	labelsByChoice: Map<string, string>;
}

const SUGGESTED_WORKTREE_LABEL_MAX_LENGTH = 32;
const FALLBACK_USER_WORKTREE_PREFIX = "un";
const FALLBACK_WORKTREE_SLUG = "worktree";

function osUsername(): string {
	try {
		return os.userInfo().username;
	} catch {
		return "";
	}
}

function currentUserId(): string {
	return process.env.USER || osUsername() || "unknown";
}

export function userWorktreePrefix(userId: string | null | undefined): string {
	const prefix = (userId ?? "")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "")
		.slice(0, 2);
	return prefix || FALLBACK_USER_WORKTREE_PREFIX;
}

function normalizeWorktreeSlug(value: string): string {
	const slug = value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "");
	return slug || FALLBACK_WORKTREE_SLUG;
}

export function suggestWorktreeLabel(goal: string, worktreeSlug: string | null, userId = currentUserId()): string {
	const prefix = userWorktreePrefix(userId);
	const slug = normalizeWorktreeSlug(worktreeSlug ?? goal);
	const maxSlugLength = Math.max(1, SUGGESTED_WORKTREE_LABEL_MAX_LENGTH - prefix.length - 1);
	const cappedSlug = slug.slice(0, maxSlugLength).replace(/-+$/g, "");
	return `${prefix}-${cappedSlug}`;
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
	return { choices, labelsByChoice };
}
