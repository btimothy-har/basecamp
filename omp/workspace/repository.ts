/**
 * Live Git identity for workspace policy. The repository handle is cached only
 * while cwd and the repository's on-disk identity are unchanged; branch state
 * is always re-read from HEAD.
 */
import { type VcsGitRepo, vcsGitDiscover } from "@oh-my-pi/pi-natives";

export interface RepositoryIdentity {
	/** Top-level of the checkout containing the cwd (linked worktrees included). */
	root: string;
	/** Primary checkout root of the owning repository. */
	primaryRoot: string;
	/** Current branch name, or null when HEAD is detached/unborn. */
	branch: string | null;
}

interface CachedHandle {
	cwd: string;
	repo: VcsGitRepo;
	repoRoot: string;
	gitDir: string;
}

export class RepositoryCache {
	#cached: CachedHandle | null = null;
	#primaryRoots = new Set<string>();

	/** Resolve live identity at `cwd`; null outside any Git repository. */
	identify(cwd: string): RepositoryIdentity | null {
		let cached = this.#cached;
		if (cached && cached.cwd === cwd) {
			try {
				const info = cached.repo.info();
				if (info.repoRoot !== cached.repoRoot || info.gitDir !== cached.gitDir) cached = null;
			} catch {
				cached = null;
			}
		} else {
			cached = null;
		}
		if (!cached) {
			let repo: VcsGitRepo | null;
			try {
				repo = vcsGitDiscover(cwd);
			} catch {
				repo = null;
			}
			if (!repo) {
				this.#cached = null;
				return null;
			}
			const info = repo.info();
			cached = { cwd, repo, repoRoot: info.repoRoot, gitDir: info.gitDir };
			this.#cached = cached;
		}
		let branch: string | null = null;
		try {
			const head = cached.repo.headSync();
			branch = typeof head.branch === "string" && head.branch.length > 0 ? head.branch : null;
		} catch {
			// An unborn repository still has a canonical checkout worth protecting.
		}
		const primaryRoot = cached.repo.primaryRoot();
		this.#primaryRoots.add(primaryRoot);
		return {
			root: cached.repo.info().repoRoot,
			primaryRoot,
			branch,
		};
	}

	/** Canonical roots identified anywhere during this live extension session. */
	primaryRoots(): string[] {
		return [...this.#primaryRoots];
	}
}
