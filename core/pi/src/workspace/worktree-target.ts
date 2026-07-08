import * as os from "node:os";

export interface ExecutionWorktreeTarget {
	worktreeLabel: string;
	branchName: string | null;
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
