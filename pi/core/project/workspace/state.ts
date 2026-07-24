/**
 * Workspace state — the shared types, the state accessors (thin reads over the
 * core workspace runtime in ./runtime.ts), and the allowed-roots registry.
 */

import { getWorkspaceRuntime, requireWorkspaceRuntime } from "./runtime.ts";

export interface RepoContext {
	isRepo: boolean;
	name: string;
	root: string;
	remoteUrl: string | null;
}

export type WorkspaceWorktreeKind = "git-worktree" | (string & {});

export interface WorkspaceWorktree {
	kind: WorkspaceWorktreeKind;
	label: string;
	path: string;
	branch: string | null;
	created: boolean;
}

export interface WorkspaceState {
	launchCwd: string;
	effectiveCwd: string;
	scratchDir: string;
	repo: RepoContext | null;
	protectedRoot: string | null;
	activeWorktree: WorkspaceWorktree | null;
	unsafeEdit: boolean;
}

export interface UnsafeEditConstraints {
	readOnly: boolean;
	hasUI: boolean;
	isSubagent: boolean;
	sandboxed: boolean;
}

export type UnsafeEditFlagResult =
	| "disabled"
	| "enabled"
	| "ignored-read-only"
	| "ignored-subagent"
	| "ignored-non-interactive";

export interface WorkspaceInitializeOptions {
	launchCwd: string;
	unsafeEditFlag: boolean;
	unsafeEditConstraints: UnsafeEditConstraints;
	/** Pi session id of a top-level session; enables session-worktree leasing. Null for subagents. */
	sessionId?: string | null;
}

export interface WorkspaceInitializeResult {
	state: WorkspaceState;
	unsafeEditResult: UnsafeEditFlagResult;
}

// --- Allowed-roots registry: a genuine multi-registrant seam (`project`
// registers "projects", the workspace session registers "logseq"). ---

export interface WorkspaceAllowedRootsProvider {
	id: string;
	roots(): string[];
}

const allowedRootProviders = new Map<string, WorkspaceAllowedRootsProvider>();

export function registerWorkspaceAllowedRootsProvider(provider: WorkspaceAllowedRootsProvider): void {
	allowedRootProviders.set(provider.id, provider);
}

export function listWorkspaceAllowedRoots(): string[] {
	return Array.from(allowedRootProviders.values()).flatMap((provider) => provider.roots());
}

// --- State accessors — thin reads over the core workspace runtime. ---

export function getWorkspaceState(): WorkspaceState | null {
	return getWorkspaceRuntime()?.current() ?? null;
}

/**
 * The current write scope (`allowed_dirs`): the directories this session may write to — the
 * active worktree, the session scratch dir, and every registered allowed-root. The main
 * checkout is never in it; with no active worktree the scope is scratch + allowed-roots.
 *
 * The write/edit guard confines structured mutations to this scope while a worktree is active;
 * the bash-reviewer will read the same scope. (Pre-handoff
 * — no worktree — the guard still blocks the protected checkout, but extending the full
 * `allowed_dirs` confinement to that case lands with the deferred guard collapse.) Each pi
 * process has its own workspace state, so an agent resolves this to its own Wn and the human
 * session to W0 — no branching.
 */
export function allowedWriteDirsFrom(state: WorkspaceState | null, allowedRoots: string[]): string[] {
	const dirs = [...allowedRoots];
	if (state?.activeWorktree) dirs.push(state.activeWorktree.path);
	if (state?.scratchDir) dirs.push(state.scratchDir);
	return dirs;
}

export function listAllowedWriteDirs(): string[] {
	return allowedWriteDirsFrom(getWorkspaceState(), listWorkspaceAllowedRoots());
}

export function requireWorkspaceState(): WorkspaceState {
	return requireWorkspaceRuntime().require();
}

export function getWorkspaceEffectiveCwd(): string {
	return getWorkspaceRuntime()?.getEffectiveCwd() ?? process.cwd();
}

export function onWorkspaceChange(listener: (state: WorkspaceState | null) => void): (() => void) | null {
	return getWorkspaceRuntime()?.onChange(listener) ?? null;
}

export function listWorkspaceWorktrees(): Promise<WorkspaceWorktree[]> {
	return requireWorkspaceRuntime().listWorktrees();
}

export function activateWorkspaceWorktree(label: string, branchName?: string | null): Promise<WorkspaceWorktree> {
	return requireWorkspaceRuntime().activateWorktree(label, branchName);
}

export function attachWorkspaceWorktreePath(path: string): Promise<WorkspaceWorktree> {
	return requireWorkspaceRuntime().attachWorktreePath(path);
}

export function initializeWorkspace(opts: WorkspaceInitializeOptions): Promise<WorkspaceInitializeResult> {
	return requireWorkspaceRuntime().initialize(opts);
}
