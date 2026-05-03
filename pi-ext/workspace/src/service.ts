import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerCwdProvider } from "../../platform/exec.ts";
import {
	type ExecutionTarget,
	type RepoContext,
	registerWorkspaceService,
	type WorkspaceService,
	type WorkspaceState,
} from "../../platform/workspace.ts";
import { SCRATCH_ROOT } from "./constants.ts";
import { resolveGitInfo } from "./repo.ts";
import { applyUnsafeEditFlag, type UnsafeEditConstraints, type UnsafeEditFlagResult } from "./unsafe-edit.ts";
import { attachWorktreeDir, getOrCreateWorktree, listWorktrees, type WorktreeResult } from "./worktree.ts";

interface WorkspaceRuntimeGlobal {
	service: WorkspaceRuntimeService | null;
}

const workspaceRuntimeKey = Symbol.for("basecamp.workspace.runtime");

type GlobalWithWorkspaceRuntime = typeof globalThis & {
	[workspaceRuntimeKey]?: WorkspaceRuntimeGlobal;
};

export interface WorkspaceInitializeOptions {
	launchCwd: string;
	unsafeEditFlag: boolean;
	unsafeEditConstraints: UnsafeEditConstraints;
}

export interface WorkspaceInitializeResult {
	state: WorkspaceState;
	unsafeEditResult: UnsafeEditFlagResult;
}

function getWorkspaceRuntimeGlobal(): WorkspaceRuntimeGlobal {
	const globalObject = globalThis as GlobalWithWorkspaceRuntime;
	globalObject[workspaceRuntimeKey] ??= { service: null };
	return globalObject[workspaceRuntimeKey];
}

function executionTargetRequiresRepo(): never {
	throw new Error("Execution targets require a git repository");
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function computeEffectiveCwd(state: WorkspaceState): string {
	const targetPath = state.executionTarget?.path;
	if (!targetPath || !state.protectedRoot) return state.launchCwd;

	if (isPathWithin(state.launchCwd, state.protectedRoot)) {
		const relative = path.relative(state.protectedRoot, state.launchCwd);
		return path.resolve(targetPath, relative);
	}

	return targetPath;
}

function worktreeToExecutionTarget(wt: WorktreeResult): ExecutionTarget {
	return {
		kind: "git-worktree",
		label: wt.label,
		path: wt.worktreeDir,
		branch: wt.branch,
		created: wt.created,
	};
}

function setWorkspaceEnv(state: WorkspaceState): void {
	process.env.BASECAMP_REPO = state.repo?.name ?? path.basename(state.scratchDir);
	process.env.BASECAMP_SCRATCH_DIR = state.scratchDir;
	process.env.BASECAMP_WORKTREE_DIR = state.executionTarget?.path ?? "";
	process.env.BASECAMP_WORKTREE_LABEL = state.executionTarget?.label ?? "";
}

export class WorkspaceRuntimeService implements WorkspaceService {
	private pi: ExtensionAPI;
	private state: WorkspaceState | null = null;
	private readonly listeners = new Set<(state: WorkspaceState | null) => void>();

	constructor(pi: ExtensionAPI) {
		this.pi = pi;
	}

	updatePi(pi: ExtensionAPI): void {
		this.pi = pi;
	}

	async initialize(opts: WorkspaceInitializeOptions): Promise<WorkspaceInitializeResult> {
		const launchCwd = path.resolve(opts.launchCwd);
		const gitInfo = await resolveGitInfo(this.pi, launchCwd);
		const repoRootOrLaunchCwd = gitInfo.toplevel ?? launchCwd;
		const repo: RepoContext | null = gitInfo.isRepo
			? {
					isRepo: true,
					name: gitInfo.repoName,
					root: repoRootOrLaunchCwd,
					remoteUrl: gitInfo.remoteUrl,
				}
			: null;
		const scratchDir = path.join(SCRATCH_ROOT, gitInfo.repoName || path.basename(repoRootOrLaunchCwd));
		const state: WorkspaceState = {
			launchCwd,
			effectiveCwd: launchCwd,
			scratchDir,
			repo,
			protectedRoot: repo?.root ?? null,
			executionTarget: null,
			unsafeEdit: false,
		};
		state.effectiveCwd = computeEffectiveCwd(state);

		const unsafeEditResult = applyUnsafeEditFlag(state, opts.unsafeEditFlag, opts.unsafeEditConstraints);
		await fs.mkdir(scratchDir, { recursive: true });

		this.state = state;
		setWorkspaceEnv(state);
		this.notify();

		return { state, unsafeEditResult };
	}

	current(): WorkspaceState | null {
		return this.state;
	}

	require(): WorkspaceState {
		if (!this.state) throw new Error("Workspace runtime is not initialized");
		return this.state;
	}

	getEffectiveCwd(): string {
		return this.state?.effectiveCwd ?? process.cwd();
	}

	async listExecutionTargets(): Promise<ExecutionTarget[]> {
		const state = this.require();
		if (!state.repo) executionTargetRequiresRepo();
		const worktrees = await listWorktrees(this.pi, state.repo.root, state.repo.name);
		return worktrees.map((wt) => ({
			kind: "git-worktree",
			label: wt.label,
			path: wt.path,
			branch: wt.branch,
			created: false,
		}));
	}

	async activateExecutionTarget(label: string): Promise<ExecutionTarget> {
		const state = this.require();
		if (!state.repo) executionTargetRequiresRepo();
		const wt = await getOrCreateWorktree(this.pi, state.repo.root, state.repo.name, label);
		return this.applyExecutionTarget(worktreeToExecutionTarget(wt));
	}

	async attachExecutionTargetPath(worktreeDir: string): Promise<ExecutionTarget> {
		const state = this.require();
		if (!state.repo) executionTargetRequiresRepo();
		const wt = await attachWorktreeDir(this.pi, state.repo.root, state.repo.name, worktreeDir);
		return this.applyExecutionTarget(worktreeToExecutionTarget(wt));
	}

	onChange(listener: (state: WorkspaceState | null) => void): () => void {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	private applyExecutionTarget(target: ExecutionTarget): ExecutionTarget {
		const state = this.require();
		state.executionTarget = target;
		state.effectiveCwd = computeEffectiveCwd(state);
		setWorkspaceEnv(state);
		this.notify();
		return target;
	}

	private notify(): void {
		for (const listener of this.listeners) listener(this.state);
	}
}

export function registerWorkspaceRuntime(pi: ExtensionAPI): WorkspaceRuntimeService {
	const runtime = getWorkspaceRuntimeGlobal();
	if (runtime.service) {
		runtime.service.updatePi(pi);
	} else {
		runtime.service = new WorkspaceRuntimeService(pi);
	}

	registerWorkspaceService(runtime.service);
	registerCwdProvider(() => runtime.service?.getEffectiveCwd() ?? process.cwd());
	return runtime.service;
}

export function requireWorkspaceRuntime(): WorkspaceRuntimeService {
	const service = getWorkspaceRuntimeGlobal().service;
	if (!service) throw new Error("Workspace runtime is not initialized");
	return service;
}
