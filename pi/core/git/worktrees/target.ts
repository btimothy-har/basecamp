import * as os from "node:os";

export interface ExecutionWorktreeTarget {
	worktreeLabel: string;
	branchName: string | null;
}

/**
 * A target for a worktree still to be provisioned. `branchName` is always minted here — a null
 * branch means "adopt whatever an existing worktree already has", which only applies to targets
 * built from an existing worktree, never to the builders below.
 */
export interface NewWorktreeTarget extends ExecutionWorktreeTarget {
	branchName: string;
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

export function currentUserId(): string {
	return process.env.USER || osUsername() || "unknown";
}

export function userWorktreePrefix(userId: string | null | undefined): string {
	const prefix = (userId ?? "")
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "")
		.slice(0, 2);
	return prefix.length === 2 ? prefix : FALLBACK_USER_WORKTREE_PREFIX;
}

export function normalizeWorktreeSlug(value: string): string {
	const slug = value
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "");
	return slug || FALLBACK_WORKTREE_SLUG;
}

function normalizeSessionTag(value: string | null | undefined): string {
	return (value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

/**
 * Session-worktree target (issue #310 Phase 3): a generic `wt/<slug>` directory (a disposable
 * cache) plus a unique `<prefix>/<tag>-<slug>` branch (the durable identity). The slug is capped so
 * the branch — the longer identifier — stays bounded; worktree-name collisions are resolved at
 * provision time by resolveAvailableWorktreeLabel, so this builder stays pure. Shared by the plan
 * handoff picker and the `/worktree` create-new flow so naming lives in one place.
 */
export function executionWorktreeTarget(
	slug: string,
	sessionTag: string,
	userId: string = currentUserId(),
): NewWorktreeTarget {
	const branchPrefix = `${userWorktreePrefix(userId)}/`;
	const normalizedSlug = normalizeWorktreeSlug(slug);
	const tag = normalizeSessionTag(sessionTag);
	const tagSegment = tag ? `${tag}-` : "";
	const baseSlug =
		tagSegment && normalizedSlug.startsWith(tagSegment) ? normalizedSlug.slice(tagSegment.length) : normalizedSlug;
	const maxSlugLength = Math.max(1, SUGGESTED_WORKTREE_LABEL_MAX_LENGTH - branchPrefix.length - tagSegment.length);
	const cappedSlug = baseSlug.slice(0, maxSlugLength).replace(/-+$/g, "") || FALLBACK_WORKTREE_SLUG;
	return {
		worktreeLabel: `wt/${cappedSlug}`,
		branchName: `${branchPrefix}${tagSegment}${cappedSlug}`,
	};
}

export function copilotWorktreeTarget(
	workName: string,
	generatedName: string,
	userId: string = currentUserId(),
): ExecutionWorktreeTarget {
	const prefix = userWorktreePrefix(userId);
	const slug = normalizeWorktreeSlug(workName);
	const branchPrefix = `${prefix}/`;
	const maxSlugLength = Math.max(1, SUGGESTED_WORKTREE_LABEL_MAX_LENGTH - branchPrefix.length);
	const cappedWorkSlug = slug.slice(0, maxSlugLength).replace(/-+$/g, "") || FALLBACK_WORKTREE_SLUG;
	return {
		worktreeLabel: `copilot/${generatedName}`,
		branchName: `${branchPrefix}${cappedWorkSlug}`,
	};
}
