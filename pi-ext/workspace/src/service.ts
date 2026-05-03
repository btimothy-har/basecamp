import * as fs from "node:fs/promises";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerCwdProvider } from "../../platform/exec.ts";
import {
	type RepoContext,
	registerWorkspaceService,
	type UnsafeEditConstraints,
	type UnsafeEditFlagResult,
	type WorkspaceInitializeOptions,
	type WorkspaceInitializeResult,
	type WorkspaceService,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "../../platform/workspace.ts";
import { SCRATCH_ROOT } from "./constants.ts";
import { resolveGitInfo } from "./repo.ts";
import { applyUnsafeEditFlag } from "./unsafe-edit.ts";
import { attachWorktreeDir, getOrCreateWorktree, listWorktrees as listGitWorktrees, type WorktreeResult } from "./worktree.ts";

interface WorkspaceRuntimeGlobal {
	service: WorkspaceRuntimeService | null;
}

const workspaceRuntimeKey = Symbol.for("basecamp.workspace.runtime");

type GlobalWithWorkspaceRuntime = typeof globalThis & {
	[workspaceRuntimeKey]?: WorkspaceRuntimeGlobal;
};

function getWorkspaceRuntimeGlobal(): WorkspaceRuntimeGlobal {
	const globalObject = globalThis as GlobalWithWorkspaceRuntime;
	globalObject[workspaceRuntimeKey] ??= { service: null };
	return globalObject[workspaceRuntimeKey];
}

function worktreeRequiresRepo(): never {
	throw new Error("Workspace worktrees require a git repository");
}

function isPathWithin(child: string, parent: string): boolean {
	const relative = path.relative(parent, child);
	return relative === "" || (!!relative && !relative.startsWith("..") && !path.isAbsolute(relative));
}

function computeEffectiveCwd(state: WorkspaceState): string {
	const targetPath = state.activeWorktree?.path;
	if (!targetPath || !state.protectedRoot) return state.launchCwd;

	if (isPathWithin(state.launchCwd, state.protectedRoot)) {
		const relative = path.relative(state.protectedRoot, state.launchCwd);
		return path.resolve(targetPath, relative);
	}

	return targetPath;
}

function worktreeResultToWorkspaceWorktree(wt: WorktreeResult): WorkspaceWorktree {
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
	process.env.BASECAMP_WORKTREE_DIR = state.activeWorktree?.path ?? "";
	process.env.BASECAMP_WORKTREE_LABEL = state.activeWorktree?.label ?? "";
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
			activeWorktree: null,
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

	async listWorktrees(): Promise<WorkspaceWorktree[]> {
		const state = this.require();
		if (!state.repo) worktreeRequiresRepo();
		const worktrees = await listGitWorktrees(this.pi, state.repo.root, state.repo.name);
		return worktrees.map((wt) => ({
			kind: "git-worktree",
			label: wt.label,
			path: wt.path,
			branch: wt.branch,
			created: false,
		}));
	}

	async activateWorktree(label: string): Promise<WorkspaceWorktree> {
		const state = this.require();
		if (!state.repo) worktreeRequiresRepo();
		const wt = await getOrCreateWorktree(this.pi, state.repo.root, state.repo.name, label);
		return this.applyWorktree(worktreeResultToWorkspaceWorktree(wt));
	}

	async attachWorktreePath(worktreeDir: string): Promise<WorkspaceWorktree> {
		const state = this.require();
		if (!state.repo) worktreeRequiresRepo();
		const wt = await attachWorktreeDir(this.pi, state.repo.root, state.repo.name, worktreeDir);
		return this.applyWorktree(worktreeResultToWorkspaceWorktree(wt));
	}

	onChange(listener: (state: WorkspaceState | null) => void): () => void {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	private applyWorktree(target: WorkspaceWorktree): WorkspaceWorktree {
		const state = this.require();
		state.activeWorktree = target;
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
