import { createDiffLoader, type DiffLoaderDeps, type DiffRepository } from "../../loader.ts";

interface FakeRepoOptions {
	root?: string;
	defaultBranch?: string | null;
	refs?: readonly string[];
	headSha?: string | null;
	mergeBase?: string | null;
	patch?: string;
	untracked?: Record<string, string | null>;
}

interface DiffCall {
	base: string;
	files?: string[];
}

export const PATCH = [
	"diff --git a/src/a.ts b/src/a.ts",
	"index 1111111..2222222 100644",
	"--- a/src/a.ts",
	"+++ b/src/a.ts",
	"@@ -1,2 +1,3 @@",
	" context",
	"-old",
	"+new",
	"+added",
	"diff --git a/src/b.ts b/src/b.ts",
	"index 3333333..4444444 100644",
	"--- a/src/b.ts",
	"+++ b/src/b.ts",
	"@@ -10 +10,2 @@",
	" ctx",
	"+more",
	"",
].join("\n");

export function fakeRepo(options: FakeRepoOptions = {}) {
	const calls = {
		mergeBase: [] as Array<[string, string]>,
		diffText: [] as DiffCall[],
		untrackedPaths: [] as Array<string[] | undefined>,
		untrackedDiff: [] as string[],
	};
	const repo: DiffRepository = {
		repositoryRoot: () => options.root ?? "/repo",
		defaultBranch: async () => (options.defaultBranch === undefined ? "main" : options.defaultBranch),
		refExists: async (name) => (options.refs ?? []).includes(name),
		headSha: async () => (options.headSha === undefined ? "head-sha" : options.headSha),
		mergeBase: async (a, b) => {
			calls.mergeBase.push([a, b]);
			return options.mergeBase === undefined ? "base-sha" : options.mergeBase;
		},
		diffText: async (diffOptions) => {
			calls.diffText.push(diffOptions);
			return options.patch ?? PATCH;
		},
		untrackedPaths: async (paths) => {
			calls.untrackedPaths.push(paths);
			return Object.keys(options.untracked ?? {});
		},
		untrackedDiff: async (path) => {
			calls.untrackedDiff.push(path);
			return Object.hasOwn(options.untracked ?? {}, path) ? (options.untracked?.[path] ?? null) : "";
		},
	};
	return { repo, calls };
}

export function loaderFor(repo: DiffRepository, env?: { BASECAMP_REPO?: string }) {
	const deps: DiffLoaderDeps = { openRepository: () => repo, env: env ?? {} };
	return createDiffLoader(deps);
}
