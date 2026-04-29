/**
 * Worktree — creation, attachment, and tool-level enforcement.
 *
 * Two-layer defense when a worktree is active:
 *   1. Prompt: env block explains active worktree/protected checkout semantics
 *   2. Tool guards:
 *      - read/edit/write/grep/find/ls: retarget relative worktree paths and block protected checkout paths
 *      - bash (tool_call): mutate event.input.command to prepend cd <worktree>
 *      - bash (user_bash / !cmd): return custom operations with worktree as cwd
 *
 * Git is the source of truth for registered worktrees. Basecamp keeps the
 * path convention ~/.worktrees/<repo>/<label>, but does not maintain a
 * separate worktree metadata registry.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { createLocalBashOperations, isToolCallEventType } from "@mariozechner/pi-coding-agent";
import type { SessionState } from "../../../platform/config";
import { getWorktreeBranchPrefix } from "../../../platform/config";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WORKTREES_DIR = path.join(os.homedir(), ".worktrees");
const WORKTREE_LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

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

function ensureWorktreeLabel(label: string): void {
	if (!WORKTREE_LABEL_RE.test(label)) {
		throw new Error(`Invalid worktree label "${label}". Use letters, numbers, dots, underscores, or hyphens.`);
	}
}

function parseWorktreeList(output: string): GitWorktreeRecord[] {
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

async function gitOutput(pi: ExtensionAPI, primaryDir: string, args: string[], timeout = 10_000): Promise<string> {
	const result = await pi.exec("git", ["-C", primaryDir, ...args], { timeout });
	if (result.code !== 0) {
		throw new Error(result.stderr.trim() || `git ${args.join(" ")} failed`);
	}
	return result.stdout.trim();
}

async function tryGitOutput(pi: ExtensionAPI, primaryDir: string, args: string[]): Promise<string | null> {
	try {
		return await gitOutput(pi, primaryDir, args);
	} catch {
		return null;
	}
}

async function gitWorktreeRecords(pi: ExtensionAPI, primaryDir: string): Promise<GitWorktreeRecord[]> {
	const output = await gitOutput(pi, primaryDir, ["worktree", "list", "--porcelain"]);
	return parseWorktreeList(output);
}

function branchName(record: GitWorktreeRecord): string {
	return record.branch ?? "detached";
}

function findWorktreeRecord(records: GitWorktreeRecord[], worktreeDir: string): GitWorktreeRecord | null {
	const resolved = path.resolve(worktreeDir);
	return records.find((record) => path.resolve(record.path) === resolved) ?? null;
}

function labelFromWorktreePath(repoName: string, worktreeDir: string): string {
	const resolvedDir = path.resolve(worktreeDir);
	const root = path.join(WORKTREES_DIR, repoName);
	const relative = path.relative(root, resolvedDir);
	const [label, ...rest] = relative.split(path.sep);
	if (!label || rest.length > 0 || relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error(`Worktree must be directly under ${root}`);
	}
	ensureWorktreeLabel(label);
	validateWorktreePath(repoName, label, resolvedDir);
	return label;
}

async function branchExists(pi: ExtensionAPI, primaryDir: string, branch: string): Promise<boolean> {
	return (await tryGitOutput(pi, primaryDir, ["rev-parse", "--verify", `refs/heads/${branch}`])) !== null;
}

async function detectDefaultBranch(pi: ExtensionAPI, primaryDir: string): Promise<string> {
	const originHead = await tryGitOutput(pi, primaryDir, [
		"symbolic-ref",
		"--quiet",
		"--short",
		"refs/remotes/origin/HEAD",
	]);
	if (originHead?.startsWith("origin/")) return originHead.slice("origin/".length);
	if (await tryGitOutput(pi, primaryDir, ["rev-parse", "--verify", "main"])) return "main";
	if (await tryGitOutput(pi, primaryDir, ["rev-parse", "--verify", "master"])) return "master";
	throw new Error("Could not determine default branch (expected origin/HEAD, main, or master)");
}

export async function validateProtectedCheckout(pi: ExtensionAPI, primaryDir: string): Promise<string> {
	const defaultBranch = await detectDefaultBranch(pi, primaryDir);
	const branch = await gitOutput(pi, primaryDir, ["branch", "--show-current"]);
	if (branch !== defaultBranch) {
		throw new Error(`Protected checkout must be on ${defaultBranch}; currently on ${branch || "detached HEAD"}`);
	}

	const status = await gitOutput(pi, primaryDir, ["status", "--porcelain"]);
	if (status) {
		throw new Error(`Protected checkout must be clean before worktree activation:\n${status}`);
	}

	return defaultBranch;
}

function validateWorktreePath(repoName: string, label: string, worktreeDir: string): void {
	const expected = path.join(WORKTREES_DIR, repoName, label);
	if (path.resolve(worktreeDir) !== path.resolve(expected)) {
		throw new Error(`Worktree path must be ${expected}`);
	}
}

export async function listWorktrees(
	pi: ExtensionAPI,
	primaryDir: string,
	repoName: string,
): Promise<WorktreeSummary[]> {
	const records = await gitWorktreeRecords(pi, primaryDir);
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
	primaryDir: string,
	repoName: string,
	worktreeDir: string,
): Promise<WorktreeResult> {
	await validateProtectedCheckout(pi, primaryDir);

	const resolvedDir = path.resolve(worktreeDir);
	const label = labelFromWorktreePath(repoName, resolvedDir);
	if (!fs.existsSync(resolvedDir) || !fs.statSync(resolvedDir).isDirectory()) {
		throw new Error(`Worktree directory not found: ${resolvedDir}`);
	}

	const record = findWorktreeRecord(await gitWorktreeRecords(pi, primaryDir), resolvedDir);
	if (!record) {
		throw new Error(`Git does not know about worktree: ${resolvedDir}`);
	}

	return { worktreeDir: resolvedDir, label, branch: branchName(record), created: false };
}

export async function getOrCreateWorktree(
	pi: ExtensionAPI,
	primaryDir: string,
	repoName: string,
	label: string,
	branchPrefix?: string,
): Promise<WorktreeResult> {
	ensureWorktreeLabel(label);
	const defaultBranch = await validateProtectedCheckout(pi, primaryDir);
	const worktreeDir = path.join(WORKTREES_DIR, repoName, label);
	const branch = `${branchPrefix ?? getWorktreeBranchPrefix()}${label}`;
	const records = await gitWorktreeRecords(pi, primaryDir);
	const existing = findWorktreeRecord(records, worktreeDir);
	if (existing) {
		return { worktreeDir, label, branch: branchName(existing), created: false };
	}
	if (fs.existsSync(worktreeDir)) {
		throw new Error(`Worktree path exists but is not registered with git: ${worktreeDir}`);
	}

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });

	const args = (await branchExists(pi, primaryDir, branch))
		? ["-C", primaryDir, "worktree", "add", worktreeDir, branch]
		: ["-C", primaryDir, "worktree", "add", "-b", branch, worktreeDir, defaultBranch];
	const result = await pi.exec("git", args, { timeout: 30_000 });
	if (result.code !== 0) {
		throw new Error(`Failed to create worktree: ${result.stderr}`);
	}

	return { worktreeDir, label, branch, created: true };
}

// ---------------------------------------------------------------------------
// Tool guards
// ---------------------------------------------------------------------------

/** Expand ~ in path (mirrors pi's path-utils expandPath). */
function expandPath(filePath: string): string {
	const normalized = filePath.startsWith("@") ? filePath.slice(1) : filePath;
	if (normalized === "~") return os.homedir();
	if (normalized.startsWith("~/")) return os.homedir() + normalized.slice(1);
	return normalized;
}

/** Shell-quote a string for safe embedding in bash commands. */
function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function isSecondaryPath(state: SessionState, resolved: string): boolean {
	return state.secondaryDirs.some((dir: string) => isPathWithin(resolved, dir));
}

const STRUCTURED_PATH_TOOLS = new Set(["read", "edit", "write", "grep", "find", "ls"]);
const STRUCTURED_MUTATION_TOOLS = new Set(["edit", "write"]);
const OPTIONAL_PATH_TOOLS = new Set(["grep", "find", "ls"]);

/**
 * Register tool_call guards for protected checkout and worktree enforcement.
 */
export function registerWorktreeGuards(pi: ExtensionAPI, getState: () => SessionState): void {
	// user_bash fires when the user types !cmd directly in pi's terminal.
	// Pi passes sessionManager.getCwd() (source repo) to the subprocess, so we
	// override operations to substitute the worktree dir as the execution cwd.
	pi.on("user_bash", async () => {
		const state = getState();
		if (!state.worktreeDir) return;

		const worktreeDir = state.worktreeDir;
		const local = createLocalBashOperations();
		return {
			operations: {
				exec: (command: string, _cwd: string, options) => local.exec(command, worktreeDir, options),
			},
		};
	});

	pi.on("tool_call", async (event) => {
		const state = getState();
		const protectedCheckout = state.primaryDir;
		const worktreeDir = state.worktreeDir;

		if (isToolCallEventType("bash", event)) {
			if (!worktreeDir) return;
			const cmd = event.input.command;
			const quoted = shellQuote(worktreeDir);
			const alreadyCd = cmd?.startsWith(`cd ${worktreeDir}`) || cmd?.startsWith(`cd ${quoted}`);
			if (cmd && !alreadyCd) {
				event.input.command = `cd ${quoted} && ${cmd}`;
			}
			return;
		}

		if (!STRUCTURED_PATH_TOOLS.has(event.toolName)) return;

		const input = event.input as { path?: string };
		if (worktreeDir && OPTIONAL_PATH_TOOLS.has(event.toolName) && !input.path) {
			input.path = worktreeDir;
			return;
		}
		if (!input.path) return;

		const expanded = expandPath(input.path);
		const isAbsolute = path.isAbsolute(expanded);
		const baseDir = worktreeDir ?? protectedCheckout;
		const resolved = isAbsolute ? path.resolve(expanded) : path.resolve(baseDir, expanded);

		if (isSecondaryPath(state, resolved)) return;

		if (!worktreeDir) {
			if (STRUCTURED_MUTATION_TOOLS.has(event.toolName) && isPathWithin(resolved, protectedCheckout)) {
				return {
					block: true,
					reason:
						`Path "${input.path}" resolves to the protected checkout (${protectedCheckout}). ` +
						"Activate an execution worktree before editing project files.",
				};
			}
			return;
		}

		if (!isAbsolute && !isPathWithin(resolved, worktreeDir)) {
			return {
				block: true,
				reason: `Relative path "${input.path}" escapes the active worktree (${worktreeDir}).`,
			};
		}

		if (isPathWithin(resolved, protectedCheckout)) {
			return {
				block: true,
				reason:
					`Path "${input.path}" resolves to the protected checkout (${protectedCheckout}). ` +
					`Use the active worktree instead: ${worktreeDir}`,
			};
		}

		if (!isAbsolute) {
			input.path = resolved;
		}
	});
}
