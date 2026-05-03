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

export type ExecutionTargetKind = "git-worktree" | (string & {});

export interface ExecutionTarget {
	kind: ExecutionTargetKind;
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
	executionTarget: ExecutionTarget | null;
	unsafeEdit: boolean;
}

export interface WorkspaceService {
	current(): WorkspaceState | null;
	require(): WorkspaceState;
	getEffectiveCwd(): string;
	listExecutionTargets(): Promise<ExecutionTarget[]>;
	activateExecutionTarget(label: string): Promise<ExecutionTarget>;
	onChange?(listener: (state: WorkspaceState | null) => void): () => void;
}

interface WorkspaceRuntime {
	service: WorkspaceService | null;
}

const workspaceKey = Symbol.for("basecamp.workspace");

type GlobalWithWorkspace = typeof globalThis & {
	[workspaceKey]?: WorkspaceRuntime;
};

function getWorkspaceRuntime(): WorkspaceRuntime {
	const globalObject = globalThis as GlobalWithWorkspace;
	globalObject[workspaceKey] ??= { service: null };
	return globalObject[workspaceKey];
}

export function registerWorkspaceService(service: WorkspaceService): void {
	getWorkspaceRuntime().service = service;
}

export function getWorkspaceService(): WorkspaceService | null {
	return getWorkspaceRuntime().service;
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

export function listWorkspaceExecutionTargets(): Promise<ExecutionTarget[]> {
	return requireWorkspaceService().listExecutionTargets();
}

export function activateWorkspaceExecutionTarget(label: string): Promise<ExecutionTarget> {
	return requireWorkspaceService().activateExecutionTarget(label);
}
