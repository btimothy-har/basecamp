/**
 * Process-scoped workspace provider registry.
 *
 * Pi loads package extension entries with separate Jiti module caches. Workspace
 * state shared by extension entries must live on globalThis rather than in a
 * module-local variable.
 */

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

export interface WorkspaceService {
	current(): WorkspaceState | null;
	require(): WorkspaceState;
	getEffectiveCwd(): string;
	listWorktrees(): Promise<WorkspaceWorktree[]>;
	activateWorktree(label: string): Promise<WorkspaceWorktree>;
	attachWorktreePath(path: string): Promise<WorkspaceWorktree>;
	onChange?(listener: (state: WorkspaceState | null) => void): () => void;
}

export interface WorkspaceAllowedRootsProvider {
	id: string;
	roots(): string[];
}

interface WorkspaceRuntime {
	service: WorkspaceService | null;
	allowedRootProviders: Map<string, WorkspaceAllowedRootsProvider>;
}

const workspaceKey = Symbol.for("basecamp.workspace");

type GlobalWithWorkspace = typeof globalThis & {
	[workspaceKey]?: WorkspaceRuntime;
};

function getWorkspaceRuntime(): WorkspaceRuntime {
	const globalObject = globalThis as GlobalWithWorkspace;
	globalObject[workspaceKey] ??= { service: null, allowedRootProviders: new Map() };
	globalObject[workspaceKey].allowedRootProviders ??= new Map();
	return globalObject[workspaceKey];
}

export function registerWorkspaceService(service: WorkspaceService): void {
	getWorkspaceRuntime().service = service;
}

export function getWorkspaceService(): WorkspaceService | null {
	return getWorkspaceRuntime().service;
}

export function registerWorkspaceAllowedRootsProvider(provider: WorkspaceAllowedRootsProvider): void {
	getWorkspaceRuntime().allowedRootProviders.set(provider.id, provider);
}

export function listWorkspaceAllowedRoots(): string[] {
	return Array.from(getWorkspaceRuntime().allowedRootProviders.values()).flatMap((provider) => provider.roots());
}

export function requireWorkspaceService(): WorkspaceService {
	const service = getWorkspaceService();
	if (!service) throw new Error("Workspace service is not initialized");
	return service;
}

export function getWorkspaceState(): WorkspaceState | null {
	return getWorkspaceService()?.current() ?? null;
}

export function requireWorkspaceState(): WorkspaceState {
	return requireWorkspaceService().require();
}

export function getWorkspaceEffectiveCwd(): string {
	return requireWorkspaceService().getEffectiveCwd();
}

export function listWorkspaceWorktrees(): Promise<WorkspaceWorktree[]> {
	return requireWorkspaceService().listWorktrees();
}

export function activateWorkspaceWorktree(label: string): Promise<WorkspaceWorktree> {
	return requireWorkspaceService().activateWorktree(label);
}

export function attachWorkspaceWorktreePath(path: string): Promise<WorkspaceWorktree> {
	return requireWorkspaceService().attachWorktreePath(path);
}
