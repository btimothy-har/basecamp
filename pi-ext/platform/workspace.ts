/**
 * Process-scoped workspace provider registry.
 *
 * Pi loads package extension entries with separate Jiti module caches. Workspace
 * state shared by extension entries must live on globalThis rather than in a
 * module-local variable.
 */

import * as path from "node:path";
import type { CustomEntry, ExtensionAPI, SessionEntry } from "@mariozechner/pi-coding-agent";

export const WORKTREE_AFFINITY_ENTRY = "workspace.worktree-affinity";

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
}

export interface WorkspaceInitializeResult {
	state: WorkspaceState;
	unsafeEditResult: UnsafeEditFlagResult;
}

export interface WorkspaceWorktreeAffinity {
	version: 1;
	repoName: string;
	repoRoot: string;
	remoteUrl: string | null;
	worktree: WorkspaceWorktree;
	updatedAt: string;
}

export interface WorkspaceService {
	initialize(opts: WorkspaceInitializeOptions): Promise<WorkspaceInitializeResult>;
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

export function initializeWorkspace(opts: WorkspaceInitializeOptions): Promise<WorkspaceInitializeResult> {
	return requireWorkspaceService().initialize(opts);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function isWorkspaceWorktree(value: unknown): value is WorkspaceWorktree {
	return (
		isRecord(value) &&
		typeof value.kind === "string" &&
		typeof value.label === "string" &&
		typeof value.path === "string" &&
		(typeof value.branch === "string" || value.branch === null) &&
		typeof value.created === "boolean"
	);
}

function isWorkspaceWorktreeAffinity(value: unknown): value is WorkspaceWorktreeAffinity {
	return (
		isRecord(value) &&
		value.version === 1 &&
		typeof value.repoName === "string" &&
		typeof value.repoRoot === "string" &&
		(typeof value.remoteUrl === "string" || value.remoteUrl === null) &&
		isWorkspaceWorktree(value.worktree) &&
		typeof value.updatedAt === "string"
	);
}

function isWorktreeAffinityEntry(entry: SessionEntry): entry is CustomEntry<unknown> {
	return entry.type === "custom" && entry.customType === WORKTREE_AFFINITY_ENTRY;
}

export function latestWorkspaceWorktreeAffinity(entries: SessionEntry[]): WorkspaceWorktreeAffinity | null {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i]!;
		if (isWorktreeAffinityEntry(entry) && isWorkspaceWorktreeAffinity(entry.data)) return entry.data;
	}
	return null;
}

export function workspaceMatchesWorktreeAffinity(
	state: WorkspaceState,
	affinity: WorkspaceWorktreeAffinity,
): boolean {
	if (!state.repo) return false;
	if (state.repo.name !== affinity.repoName) return false;
	if (path.resolve(state.repo.root) !== path.resolve(affinity.repoRoot)) return false;
	if (state.repo.remoteUrl && affinity.remoteUrl && state.repo.remoteUrl !== affinity.remoteUrl) return false;
	return true;
}

export function appendWorkspaceWorktreeAffinity(
	pi: ExtensionAPI,
	state: WorkspaceState,
	target: WorkspaceWorktree,
): void {
	if (!state.repo) return;

	pi.appendEntry(WORKTREE_AFFINITY_ENTRY, {
		version: 1,
		repoName: state.repo.name,
		repoRoot: state.repo.root,
		remoteUrl: state.repo.remoteUrl,
		worktree: target,
		updatedAt: new Date().toISOString(),
	} satisfies WorkspaceWorktreeAffinity);
}
