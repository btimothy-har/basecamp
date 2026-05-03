import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { WORKTREE_BRANCH_PREFIX, WORKTREE_LABEL_RE, WORKTREES_ROOT } from "./constants";
import { branchExists, detectDefaultBranch, gitOutput } from "./repo";

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

interface GitWorktreeRecord {
	path: string;
	branch: string | null;
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
			current = { path: line.slice("worktree ".length), branch: null };
		} else if (current && line.startsWith("branch ")) {
			const ref = line.slice("branch ".length);
			current.branch = ref.startsWith("refs/heads/") ? ref.slice("refs/heads/".length) : ref;
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

export function labelFromWorktreePath(repoName: string, worktreeDir: string): string {
	const resolvedDir = path.resolve(worktreeDir);
	const root = path.join(WORKTREES_ROOT, repoName);
	const relative = path.relative(root, resolvedDir);
	const [label, ...rest] = relative.split(path.sep);
	if (!label || rest.length > 0 || relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error(`Worktree must be directly under ${root}`);
	}
	ensureWorktreeLabel(label);
	validateWorktreePath(repoName, label, resolvedDir);
	return label;
}

export function validateWorktreePath(repoName: string, label: string, worktreeDir: string): void {
	const expected = path.join(WORKTREES_ROOT, repoName, label);
	if (path.resolve(worktreeDir) !== path.resolve(expected)) {
		throw new Error(`Worktree path must be ${expected}`);
	}
}

export function ensureWorktreeLabel(label: string): void {
	if (!WORKTREE_LABEL_RE.test(label)) {
		throw new Error(`Invalid worktree label "${label}". Use letters, numbers, dots, underscores, or hyphens.`);
	}
}

export async function validateProtectedCheckout(pi: ExtensionAPI, repoRoot: string): Promise<string> {
	const defaultBranch = await detectDefaultBranch(pi, repoRoot);
	const branch = await gitOutput(pi, repoRoot, ["branch", "--show-current"]);
	if (branch !== defaultBranch) {
		throw new Error(`Protected checkout must be on ${defaultBranch}; currently on ${branch || "detached HEAD"}`);
	}

	const status = await gitOutput(pi, repoRoot, ["status", "--porcelain"]);
	if (status) {
		throw new Error(`Protected checkout must be clean before worktree activation:\n${status}`);
	}

	return defaultBranch;
}

export async function listWorktrees(pi: ExtensionAPI, repoRoot: string, repoName: string): Promise<WorktreeSummary[]> {
	const records = await gitWorktreeRecords(pi, repoRoot);
	return records
		.map((record) => {
			try {
				const label = labelFromWorktreePath(repoName, record.path);
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
	if (!fs.existsSync(resolvedDir) || !fs.statSync(resolvedDir).isDirectory()) {
		throw new Error(`Worktree directory not found: ${resolvedDir}`);
	}

	const record = findWorktreeRecord(await gitWorktreeRecords(pi, repoRoot), resolvedDir);
	if (!record) {
		throw new Error(`Git does not know about worktree: ${resolvedDir}`);
	}

	return { worktreeDir: resolvedDir, label, branch: branchName(record), created: false };
}

export async function getOrCreateWorktree(
	pi: ExtensionAPI,
	repoRoot: string,
	repoName: string,
	label: string,
	branchPrefix = WORKTREE_BRANCH_PREFIX,
): Promise<WorktreeResult> {
	ensureWorktreeLabel(label);
	const defaultBranch = await validateProtectedCheckout(pi, repoRoot);
	const worktreeDir = path.join(WORKTREES_ROOT, repoName, label);
	const branch = `${branchPrefix}${label}`;
	const records = await gitWorktreeRecords(pi, repoRoot);
	const existing = findWorktreeRecord(records, worktreeDir);
	if (existing) {
		return { worktreeDir, label, branch: branchName(existing), created: false };
	}
	if (fs.existsSync(worktreeDir)) {
		throw new Error(`Worktree path exists but is not registered with git: ${worktreeDir}`);
	}

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });

	const args = (await branchExists(pi, repoRoot, branch))
		? ["-C", repoRoot, "worktree", "add", worktreeDir, branch]
		: ["-C", repoRoot, "worktree", "add", "-b", branch, worktreeDir, defaultBranch];
	const result = await pi.exec("git", args, { timeout: 30_000 });
	if (result.code !== 0) {
		throw new Error(`Failed to create worktree: ${result.stderr}`);
	}

	return { worktreeDir, label, branch, created: true };
}
