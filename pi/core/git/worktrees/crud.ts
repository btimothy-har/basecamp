import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { WORKTREE_BRANCH_PREFIX, WORKTREE_LABEL_RE, worktreesRoot } from "#core/git/constants.ts";
import { branchExists, detectDefaultBranch, gitOutput } from "#core/git/repo.ts";

export interface WorktreeResult {
	worktreeDir: string;
	label: string;
	branch: string;
	created: boolean;
}

export interface WorktreeSummary {
	label: string;
	path: string;
	branch: string;
}

export interface GitWorktreeRecord {
	path: string;
	branch: string | null;
	locked: boolean;
	lockReason: string | null;
}

export function parseWorktreeList(output: string): GitWorktreeRecord[] {
	const records: GitWorktreeRecord[] = [];
	let current: GitWorktreeRecord | null = null;

	for (const line of `${output}\n`.split("\n")) {
		if (!line.trim()) {
			if (current) records.push(current);
			current = null;
			continue;
		}
		if (line.startsWith("worktree ")) {
			if (current) records.push(current);
			current = { path: line.slice("worktree ".length), branch: null, locked: false, lockReason: null };
		} else if (current && line.startsWith("branch ")) {
			const ref = line.slice("branch ".length);
			current.branch = ref.startsWith("refs/heads/") ? ref.slice("refs/heads/".length) : ref;
		} else if (current && (line === "locked" || line.startsWith("locked "))) {
			current.locked = true;
			current.lockReason = line === "locked" ? null : line.slice("locked ".length);
		}
	}

	return records;
}

export async function gitWorktreeRecords(pi: ExtensionAPI, repoRoot: string): Promise<GitWorktreeRecord[]> {
	const output = await gitOutput(pi, repoRoot, ["worktree", "list", "--porcelain"]);
	return parseWorktreeList(output);
}

export function branchName(record: GitWorktreeRecord): string {
	return record.branch ?? "detached";
}

export function findWorktreeRecord(records: GitWorktreeRecord[], worktreeDir: string): GitWorktreeRecord | null {
	const resolved = path.resolve(worktreeDir);
	return records.find((record) => path.resolve(record.path) === resolved) ?? null;
}

function labelFromRelativeWorktreePath(relative: string): string | null {
	const parts = relative.split(path.sep);
	if (parts.length === 1) return parts[0] || null;
	if (parts.length === 2 && isNestedWorktreeNamespace(parts[0])) return parts.join("/");
	return null;
}

export function labelFromWorktreePath(repoName: string, worktreeDir: string): string {
	const resolvedDir = path.resolve(worktreeDir);
	const root = path.join(worktreesRoot(), repoName);
	const relative = path.relative(root, resolvedDir);
	if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error(`Worktree must be a valid workspace worktree path under ${root}`);
	}

	const label = labelFromRelativeWorktreePath(relative);
	if (!label) {
		throw new Error(`Worktree must be a valid workspace worktree path under ${root}`);
	}
	ensureWorktreeLabel(label);
	validateWorktreePath(repoName, label, resolvedDir);
	return label;
}

export function validateWorktreePath(repoName: string, label: string, worktreeDir: string): void {
	const expected = path.join(worktreesRoot(), repoName, label);
	if (path.resolve(worktreeDir) !== path.resolve(expected)) {
		throw new Error(`Worktree path must be ${expected}`);
	}
}

function isMissingPathError(error: unknown): boolean {
	return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}

export function validateNoSymlinkedWorktreePath(worktreeDir: string, root = worktreesRoot()): void {
	const resolvedRoot = path.resolve(root);
	const resolvedDir = path.resolve(worktreeDir);
	const relative = path.relative(resolvedRoot, resolvedDir);
	if (relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error(`Worktree path must be under ${resolvedRoot}`);
	}

	const componentPaths = [resolvedRoot];
	let current = resolvedRoot;
	for (const part of relative.split(path.sep).filter(Boolean)) {
		current = path.join(current, part);
		componentPaths.push(current);
	}

	for (const componentPath of componentPaths) {
		try {
			if (fs.lstatSync(componentPath).isSymbolicLink()) {
				throw new Error(`Worktree path must not contain symlinks: ${componentPath}`);
			}
		} catch (error) {
			if (isMissingPathError(error)) return;
			throw error;
		}
	}
}

// `agent-<id>` is the reserved namespace for dispatched agents' transient workspaces.
// Distinct `agent-` prefix ⇒ disjoint from the human-facing `wt`/`wt-xx`/`copilot` namespaces,
// so no user label can collide. `wt/<slug>` is the generic session-worktree namespace (issue #310
// Phase 3); `wt-xx/<slug>` stays accepted so pre-Phase-3 worktrees age out naturally.
const NESTED_WORKTREE_NAMESPACE_RE = /^(?:wt(?:-[a-z0-9]{2})?|copilot|agent-[a-z0-9]+)$/;
const NESTED_WORKTREE_LABEL_RE = /^(?:wt(?:-[a-z0-9]{2})?|copilot|agent-[a-z0-9]+)\/[A-Za-z0-9][A-Za-z0-9._-]*$/;

function isNestedWorktreeNamespace(value: string | undefined): boolean {
	return typeof value === "string" && NESTED_WORKTREE_NAMESPACE_RE.test(value);
}

export function ensureWorktreeLabel(label: string): void {
	if (!WORKTREE_LABEL_RE.test(label) && !NESTED_WORKTREE_LABEL_RE.test(label)) {
		throw new Error(
			`Invalid worktree label "${label}". Use a direct label, wt/name, wt-xx/name, or copilot/name with safe characters.`,
		);
	}
}

/**
 * Assert the protected checkout is on its default branch before provisioning a worktree from it.
 * A dirty checkout is deliberately allowed: worktrees are cut from HEAD, so uncommitted WIP stays
 * in the checkout and is never carried across (issue #310 Phase 3). The default-branch clause is a
 * cheap invariant — bare pi never leaves the default branch — kept as a corruption guard.
 */
export async function validateProtectedCheckout(pi: ExtensionAPI, repoRoot: string): Promise<string> {
	const defaultBranch = await detectDefaultBranch(pi, repoRoot);
	const branch = await gitOutput(pi, repoRoot, ["branch", "--show-current"]);
	if (branch !== defaultBranch) {
		throw new Error(`Protected checkout must be on ${defaultBranch}; currently on ${branch || "detached HEAD"}`);
	}

	return defaultBranch;
}

export async function listWorktrees(pi: ExtensionAPI, repoRoot: string, repoName: string): Promise<WorktreeSummary[]> {
	const records = await gitWorktreeRecords(pi, repoRoot);
	return records
		.map((record) => {
			try {
				const label = labelFromWorktreePath(repoName, record.path);
				validateNoSymlinkedWorktreePath(record.path);
				return { label, path: path.resolve(record.path), branch: branchName(record) };
			} catch {
				return null;
			}
		})
		.filter((wt): wt is WorktreeSummary => wt !== null)
		.sort((a, b) => a.label.localeCompare(b.label));
}

export async function attachWorktreeDir(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	worktreeDir: string,
): Promise<WorktreeResult> {
	await validateProtectedCheckout(pi, repoRoot);

	const resolvedDir = path.resolve(worktreeDir);
	const label = labelFromWorktreePath(repoName, resolvedDir);
	validateNoSymlinkedWorktreePath(resolvedDir);
	if (!fs.existsSync(resolvedDir) || !fs.statSync(resolvedDir).isDirectory()) {
		throw new Error(`Worktree directory not found: ${resolvedDir}`);
	}

	const record = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), resolvedDir);
	if (!record) {
		throw new Error(`Git does not know about worktree: ${resolvedDir}`);
	}

	return { worktreeDir: resolvedDir, label, branch: branchName(record), created: false };
}

/**
 * When `lockReason` is set, a newly created worktree is locked atomically (`git worktree add
 * --lock --reason`), so no cleanup process can observe it unlocked between creation and a
 * later lock call — the createAgentWorktree precedent. Ignored on the reuse path: refreshing
 * an existing worktree's lock is the caller's job.
 */
export async function getOrCreateWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	label: string,
	branchOverride?: string | null,
	lockReason?: string,
): Promise<WorktreeResult> {
	ensureWorktreeLabel(label);
	const defaultBranch = await validateProtectedCheckout(pi, repoRoot);
	const worktreeDir = path.join(worktreesRoot(), repoName, label);
	validateNoSymlinkedWorktreePath(worktreeDir);
	const requestedBranch = branchOverride?.trim();
	const records = await gitWorktreeRecords(pi, repoRoot);
	const existing = findWorktreeRecord(records, worktreeDir);
	if (existing) {
		return { worktreeDir, label, branch: branchName(existing), created: false };
	}
	if (fs.existsSync(worktreeDir)) {
		throw new Error(`Worktree path exists but is not registered with git: ${worktreeDir}`);
	}
	// Deriving `wt/<label>` only makes sense for a direct label; prefixing a namespaced one yields a
	// meaningless branch (`wt/wt/<slug>`, `wt/copilot/<slug>`). Reaching here with a namespaced label
	// and no branch means the caller meant to adopt a worktree that no longer exists, so fail loudly
	// rather than silently minting a new branch the caller never asked for.
	if (!requestedBranch && label.includes("/")) {
		throw new Error(
			`Worktree ${label} no longer exists and no branch was given to rebuild it from. Choose another worktree, or create one.`,
		);
	}
	const branch = requestedBranch || `${WORKTREE_BRANCH_PREFIX}${label}`;

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });

	const lockArgs = lockReason ? ["--lock", "--reason", lockReason] : [];
	const args = (await branchExists(pi, repoRoot, branch))
		? ["-C", repoRoot, "worktree", "add", ...lockArgs, worktreeDir, branch]
		: ["-C", repoRoot, "worktree", "add", ...lockArgs, "-b", branch, worktreeDir, defaultBranch];
	const result = await pi.exec("git", args, { timeout: 30_000 });
	if (result.code !== 0) {
		throw new Error(`Failed to create worktree: ${result.stderr}`);
	}

	return { worktreeDir, label, branch, created: true };
}

const MAX_WORKTREE_LABEL_ATTEMPTS = 100;

/**
 * Resolve a worktree label safe to provision on `branch`: the base label when its directory is
 * free or already holds `branch`, otherwise `<base>-2`, `<base>-3`, … skipping any directory
 * occupied by a DIFFERENT branch. Generic `wt/<slug>` labels (issue #310 Phase 3) can otherwise
 * silently adopt an unrelated same-slug worktree — e.g. a dirty survivor — via getOrCreateWorktree's
 * reuse-if-registered. Copilot/workstream provisioning keeps calling getOrCreateWorktree directly
 * (its slug is globally unique), so its idempotent reuse is unaffected.
 */
export async function resolveAvailableWorktreeLabel(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	baseLabel: string,
	branch: string,
): Promise<string> {
	const records = await gitWorktreeRecords(pi, repoRoot);
	for (let attempt = 1; attempt <= MAX_WORKTREE_LABEL_ATTEMPTS; attempt++) {
		const label = attempt === 1 ? baseLabel : `${baseLabel}-${attempt}`;
		const worktreeDir = path.join(worktreesRoot(), repoName, label);
		const existing = findWorktreeRecord(records, worktreeDir);
		if (existing) {
			if (branchName(existing) === branch) return label;
		} else if (!fs.existsSync(worktreeDir)) {
			return label;
		}
	}
	throw new Error(
		`Could not find an available worktree label for "${baseLabel}" after ${MAX_WORKTREE_LABEL_ATTEMPTS} attempts`,
	);
}
