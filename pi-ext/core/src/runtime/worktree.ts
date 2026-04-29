/**
 * Worktree — creation, attachment, and tool-level enforcement.
 *
 * Two-layer defense when a worktree is active:
 *   1. Prompt: env block tells model to use worktree dir with absolute paths
 *   2. Tool guards:
 *      - read/edit/write/grep/find/ls: retarget relative worktree paths and block protected checkout paths
 *      - bash (tool_call): mutate event.input.command to prepend cd <worktree>
 *      - bash (user_bash / !cmd): return custom operations with worktree as cwd
 *
 * Worktree metadata is stored in ~/.worktrees/<repo>/.meta/<label>.json.
 * This module reads that metadata and creates worktrees via git CLI.
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
	createdAt: string;
}

interface WorktreeMetadata {
	name?: string;
	path?: string;
	branch?: string;
	created_at?: string;
	project?: string;
	repo_name?: string;
	source_dir?: string;
}

function resolveExistingPath(value: string): string {
	return fs.realpathSync.native(value);
}

function ensureWorktreeLabel(label: string): void {
	if (!WORKTREE_LABEL_RE.test(label)) {
		throw new Error(`Invalid worktree label "${label}". Use letters, numbers, dots, underscores, or hyphens.`);
	}
}

function metadataPath(repoName: string, label: string): string {
	return path.join(WORKTREES_DIR, repoName, ".meta", `${label}.json`);
}

function readMetadata(filePath: string): WorktreeMetadata {
	try {
		return JSON.parse(fs.readFileSync(filePath, "utf8"));
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		throw new Error(`Failed to read worktree metadata: ${msg}`);
	}
}

export function listWorktrees(repoName: string): WorktreeSummary[] {
	const metaDir = path.join(WORKTREES_DIR, repoName, ".meta");
	if (!fs.existsSync(metaDir) || !fs.statSync(metaDir).isDirectory()) return [];

	const worktrees: WorktreeSummary[] = [];
	for (const entry of fs.readdirSync(metaDir, { withFileTypes: true })) {
		if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
		try {
			const meta = readMetadata(path.join(metaDir, entry.name));
			const label = meta.name ?? path.basename(entry.name, ".json");
			const worktreePath = meta.path ?? path.join(WORKTREES_DIR, repoName, label);
			if (!fs.existsSync(worktreePath) || !fs.statSync(worktreePath).isDirectory()) continue;
			worktrees.push({
				label,
				path: worktreePath,
				branch: meta.branch ?? `${getWorktreeBranchPrefix()}${label}`,
				createdAt: meta.created_at ?? "",
			});
		} catch {}
	}

	return worktrees.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function validateMetadata(
	meta: WorktreeMetadata,
	opts: { primaryDir: string; repoName: string; label: string; worktreeDir: string },
): void {
	if (meta.name && meta.name !== opts.label) {
		throw new Error(`Worktree metadata label mismatch: expected ${opts.label}, found ${meta.name}`);
	}
	if (meta.repo_name && meta.repo_name !== opts.repoName) {
		throw new Error(`Worktree metadata repo mismatch: expected ${opts.repoName}, found ${meta.repo_name}`);
	}
	if (meta.path && path.resolve(meta.path) !== path.resolve(opts.worktreeDir)) {
		throw new Error(`Worktree metadata path mismatch: expected ${opts.worktreeDir}, found ${meta.path}`);
	}
	if (!meta.source_dir) {
		throw new Error("Worktree metadata is missing source_dir");
	}
	if (resolveExistingPath(meta.source_dir) !== resolveExistingPath(opts.primaryDir)) {
		throw new Error(`Worktree source mismatch: expected ${opts.primaryDir}, found ${meta.source_dir}`);
	}
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

export async function attachWorktreeDir(
	pi: ExtensionAPI,
	primaryDir: string,
	repoName: string,
	worktreeDir: string,
): Promise<WorktreeResult> {
	await validateProtectedCheckout(pi, primaryDir);

	const resolvedDir = path.resolve(worktreeDir);
	const relative = path.relative(path.join(WORKTREES_DIR, repoName), resolvedDir);
	const [label, ...rest] = relative.split(path.sep);
	if (!label || rest.length > 0 || relative.startsWith("..") || path.isAbsolute(relative)) {
		throw new Error(`Worktree must be directly under ${path.join(WORKTREES_DIR, repoName)}`);
	}
	ensureWorktreeLabel(label);
	validateWorktreePath(repoName, label, resolvedDir);
	if (!fs.existsSync(resolvedDir) || !fs.statSync(resolvedDir).isDirectory()) {
		throw new Error(`Worktree directory not found: ${resolvedDir}`);
	}

	const metaFile = metadataPath(repoName, label);
	if (!fs.existsSync(metaFile)) {
		throw new Error(`Worktree metadata not found: ${metaFile}`);
	}
	const meta = readMetadata(metaFile);
	validateMetadata(meta, { primaryDir, repoName, label, worktreeDir: resolvedDir });

	return {
		worktreeDir: resolvedDir,
		label,
		branch: meta.branch ?? `${getWorktreeBranchPrefix()}${label}`,
		created: false,
	};
}

export async function getOrCreateWorktree(
	pi: ExtensionAPI,
	primaryDir: string,
	repoName: string,
	label: string,
	projectName: string,
	branchPrefix?: string,
): Promise<WorktreeResult> {
	ensureWorktreeLabel(label);
	const defaultBranch = await validateProtectedCheckout(pi, primaryDir);
	const worktreeDir = path.join(WORKTREES_DIR, repoName, label);
	const prefix = branchPrefix ?? getWorktreeBranchPrefix();
	const branch = `${prefix}${label}`;
	const metaDir = path.join(WORKTREES_DIR, repoName, ".meta");
	const metaFile = metadataPath(repoName, label);

	if (fs.existsSync(worktreeDir)) {
		if (!fs.existsSync(metaFile)) {
			throw new Error(`Worktree metadata not found: ${metaFile}`);
		}
		const meta = readMetadata(metaFile);
		validateMetadata(meta, { primaryDir, repoName, label, worktreeDir });
		return { worktreeDir, label, branch: meta.branch ?? branch, created: false };
	}

	fs.mkdirSync(path.dirname(worktreeDir), { recursive: true });

	const result = await pi.exec("git", ["-C", primaryDir, "worktree", "add", "-b", branch, worktreeDir, defaultBranch], {
		timeout: 30_000,
	});
	if (result.code !== 0) {
		throw new Error(`Failed to create worktree: ${result.stderr}`);
	}

	fs.mkdirSync(metaDir, { recursive: true });
	const meta = {
		name: label,
		path: worktreeDir,
		branch,
		created_at: new Date().toISOString(),
		project: projectName,
		repo_name: repoName,
		source_dir: primaryDir,
	};
	fs.writeFileSync(metaFile, JSON.stringify(meta, null, 2));

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
