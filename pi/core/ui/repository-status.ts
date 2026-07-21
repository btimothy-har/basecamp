import { existsSync, readFileSync, statSync, watch } from "node:fs";
import { dirname, join, resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { lookupPullRequestStatus, type PullRequestStatus } from "../git/pr-status.ts";
import { getWorkspaceEffectiveCwd, getWorkspaceState, onWorkspaceChange } from "../project/workspace/state.ts";

const PULL_REQUEST_REFRESH_MS = 5 * 60 * 1_000;

type PullRequestLookup = (pi: ExtensionAPI, cwd: string, signal?: AbortSignal) => Promise<PullRequestStatus | null>;

type WatchDirectory = (
	directory: string,
	listener: (event: string, filename: string | Buffer | null) => void,
) => { close(): void };

export interface RepositoryTarget {
	directory: string;
	fallbackBranch: string | null;
}

export interface RepositoryStatusOptions {
	getTarget(): RepositoryTarget;
	subscribeTarget(listener: () => void): (() => void) | null;
	lookupPullRequest?: PullRequestLookup;
	watchDirectory?: WatchDirectory;
	setIntervalFn?: typeof setInterval;
	clearIntervalFn?: typeof clearInterval;
}

interface FooterBranchData {
	getGitBranch(): string | null;
	onBranchChange(listener: () => void): () => void;
}

interface ActiveLookup {
	controller: AbortController;
	generation: number;
}

function resolveGitHeadPath(startDir: string): string | null {
	let directory = resolve(startDir);
	while (true) {
		try {
			const gitPath = join(directory, ".git");
			if (existsSync(gitPath)) {
				const stat = statSync(gitPath);
				if (stat.isDirectory()) {
					const headPath = join(gitPath, "HEAD");
					return existsSync(headPath) ? headPath : null;
				}

				const content = readFileSync(gitPath, "utf8").trim();
				if (!content.startsWith("gitdir: ")) return null;
				const gitDirectory = resolve(directory, content.slice(8).trim());
				const headPath = join(gitDirectory, "HEAD");
				return existsSync(headPath) ? headPath : null;
			}
		} catch {
			return null;
		}

		const parent = dirname(directory);
		if (parent === directory) return null;
		directory = parent;
	}
}

function safeBranchName(branch: string | null): string | null {
	if (!branch) return null;
	for (const character of branch) {
		const codePoint = character.codePointAt(0);
		if (codePoint !== undefined && (codePoint < 0x20 || codePoint === 0x7f)) return null;
	}
	return branch;
}

function readBranchFromHead(headPath: string): string | null {
	try {
		const content = readFileSync(headPath, "utf8").trim();
		if (content.startsWith("ref: refs/heads/")) return safeBranchName(content.slice(16));
		return "detached";
	} catch {
		return null;
	}
}

function pullRequestsEqual(left: PullRequestStatus | null, right: PullRequestStatus): boolean {
	return (
		left?.number === right.number &&
		left.url === right.url &&
		left.state === right.state &&
		left.isDraft === right.isDraft
	);
}

export class RepositoryStatusTracker {
	private readonly pi: ExtensionAPI;
	private readonly onChange: () => void;
	private readonly getTargetValue: () => RepositoryTarget;
	private readonly lookupPullRequest: PullRequestLookup;
	private readonly watchDirectory: WatchDirectory;
	private readonly clearIntervalFn: typeof clearInterval;
	private readonly unsubscribeTarget: (() => void) | null;
	private readonly refreshTimer: ReturnType<typeof setInterval>;
	private targetDirectory: string | null = null;
	private fallbackBranch: string | null = null;
	private branchCache: string | null = null;
	private headWatcher: { close(): void } | null = null;
	private pullRequest: PullRequestStatus | null = null;
	private pullRequestKey: string | null = null;
	private activeLookup: ActiveLookup | null = null;
	private lookupGeneration = 0;
	private refreshPending = false;
	private disposed = false;

	constructor(pi: ExtensionAPI, onChange: () => void, options: RepositoryStatusOptions) {
		this.pi = pi;
		this.onChange = onChange;
		this.getTargetValue = options.getTarget;
		this.lookupPullRequest = options.lookupPullRequest ?? lookupPullRequestStatus;
		this.watchDirectory = options.watchDirectory ?? ((directory, listener) => watch(directory, listener));
		this.clearIntervalFn = options.clearIntervalFn ?? clearInterval;
		this.unsubscribeTarget = options.subscribeTarget(() => this.syncTarget());

		const setIntervalFn = options.setIntervalFn ?? setInterval;
		this.refreshTimer = setIntervalFn(() => this.refresh(), PULL_REQUEST_REFRESH_MS);
		this.refreshTimer.unref?.();
		this.syncTarget();
	}

	getBranch(): string | null {
		return safeBranchName(this.branchCache ?? this.fallbackBranch);
	}

	getPullRequest(): PullRequestStatus | null {
		return this.pullRequest;
	}

	refresh(): void {
		if (this.disposed || !this.targetDirectory || !this.pullRequestKey) return;
		if (this.activeLookup) {
			this.refreshPending = true;
			return;
		}

		const directory = this.targetDirectory;
		const key = this.pullRequestKey;
		const controller = new AbortController();
		const generation = ++this.lookupGeneration;
		this.activeLookup = { controller, generation };

		void this.runLookup(directory, key, controller, generation);
	}

	dispose(): void {
		if (this.disposed) return;
		this.disposed = true;
		this.unsubscribeTarget?.();
		this.clearIntervalFn(this.refreshTimer);
		this.closeHeadWatcher();
		this.cancelLookup();
		this.targetDirectory = null;
		this.fallbackBranch = null;
		this.branchCache = null;
		this.pullRequest = null;
		this.pullRequestKey = null;
	}

	private syncTarget(): void {
		if (this.disposed) return;
		const target = this.getTargetValue();
		const directory = resolve(target.directory);
		const targetChanged = directory !== this.targetDirectory;
		const previousBranch = this.getBranch();

		this.fallbackBranch = target.fallbackBranch;
		if (targetChanged) {
			this.closeHeadWatcher();
			this.targetDirectory = directory;
			const headPath = resolveGitHeadPath(directory);
			this.branchCache = headPath ? readBranchFromHead(headPath) : null;
			if (headPath) this.startHeadWatcher(directory, headPath);
		}

		const pullRequestTargetChanged = this.syncPullRequestTarget();
		if (targetChanged || previousBranch !== this.getBranch() || pullRequestTargetChanged) this.onChange();
	}

	private startHeadWatcher(directory: string, headPath: string): void {
		try {
			this.headWatcher = this.watchDirectory(dirname(headPath), (_event, filename) => {
				if (this.targetDirectory !== directory || (filename && filename.toString() !== "HEAD")) return;

				const previousBranch = this.getBranch();
				this.branchCache = readBranchFromHead(headPath);
				const pullRequestTargetChanged = this.syncPullRequestTarget();
				if (previousBranch !== this.getBranch() || pullRequestTargetChanged) this.onChange();
			});
		} catch {
			this.headWatcher = null;
		}
	}

	private syncPullRequestTarget(): boolean {
		const branch = this.getBranch();
		const nextKey =
			this.targetDirectory && branch && branch !== "detached" ? `${this.targetDirectory}\0${branch}` : null;
		if (nextKey === this.pullRequestKey) return false;

		this.cancelLookup();
		this.pullRequestKey = nextKey;
		this.pullRequest = null;
		if (nextKey) this.refresh();
		return true;
	}

	private async runLookup(
		directory: string,
		key: string,
		controller: AbortController,
		generation: number,
	): Promise<void> {
		const next = await this.lookupPullRequest(this.pi, directory, controller.signal).catch(() => null);
		if (
			next &&
			!this.disposed &&
			generation === this.lookupGeneration &&
			key === this.pullRequestKey &&
			!pullRequestsEqual(this.pullRequest, next)
		) {
			this.pullRequest = next;
			this.onChange();
		}

		if (this.activeLookup?.generation !== generation) return;
		this.activeLookup = null;
		if (this.refreshPending) {
			this.refreshPending = false;
			this.refresh();
		}
	}

	private cancelLookup(): void {
		this.lookupGeneration += 1;
		this.activeLookup?.controller.abort();
		this.activeLookup = null;
		this.refreshPending = false;
	}

	private closeHeadWatcher(): void {
		this.headWatcher?.close();
		this.headWatcher = null;
	}
}

export function createFooterRepositoryStatusTracker(
	pi: ExtensionAPI,
	footerData: FooterBranchData,
	onChange: () => void,
): RepositoryStatusTracker {
	return new RepositoryStatusTracker(pi, onChange, {
		getTarget: () => {
			const workspace = getWorkspaceState();
			const effectiveCwd = getWorkspaceEffectiveCwd();
			return {
				directory: workspace?.activeWorktree?.path ?? effectiveCwd,
				fallbackBranch: workspace?.activeWorktree?.branch ?? footerData.getGitBranch(),
			};
		},
		subscribeTarget: (listener) => {
			const unsubscribeBranch = footerData.onBranchChange(listener);
			const unsubscribeWorkspace = onWorkspaceChange(listener);
			return () => {
				unsubscribeBranch();
				unsubscribeWorkspace?.();
			};
		},
	});
}
