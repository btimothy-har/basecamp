import { describe, expect, test } from "bun:test";
import { createDiffLoader } from "../loader.ts";
import { fakeRepo, loaderFor, PATCH } from "./support/loader-harness.ts";

describe("loadDiff scope resolution", () => {
	test("diffs merge-base(origin/<default>, HEAD) through the working tree", async () => {
		const { repo, calls } = fakeRepo({ refs: ["origin/main"] });
		const snapshot = await loaderFor(repo)("/repo");

		expect(calls.mergeBase).toEqual([["origin/main", "HEAD"]]);
		expect(calls.diffText).toEqual([{ base: "base-sha" }]);
		expect(snapshot).toMatchObject({
			repositoryRoot: "/repo",
			repository: "repo",
			defaultBranch: "main",
			baseRevision: "base-sha",
			headRevision: "head-sha",
			patch: PATCH,
		});
	});

	test("falls back to the local default branch when no remote-tracking ref exists", async () => {
		const { repo, calls } = fakeRepo();
		const snapshot = await loaderFor(repo)("/repo");

		expect(calls.mergeBase).toEqual([["main", "HEAD"]]);
		expect(snapshot.defaultBranch).toBe("main");
	});

	test("falls back to main, then master, when no default branch is detected", async () => {
		const main = fakeRepo({ defaultBranch: null, refs: ["main"] });
		expect((await loaderFor(main.repo)("/repo")).defaultBranch).toBe("main");
		expect(main.calls.mergeBase).toEqual([["main", "HEAD"]]);

		const master = fakeRepo({ defaultBranch: null, refs: ["master"] });
		expect((await loaderFor(master.repo)("/repo")).defaultBranch).toBe("master");
	});

	test("throws when no default branch resolves", async () => {
		const { repo } = fakeRepo({ defaultBranch: null });
		await expect(loaderFor(repo)("/repo")).rejects.toThrow("default branch");
	});

	test("throws when HEAD is unborn", async () => {
		const { repo } = fakeRepo({ headSha: null });
		await expect(loaderFor(repo)("/repo")).rejects.toThrow("no commits");
	});

	test("throws when no merge base exists", async () => {
		const { repo } = fakeRepo({ mergeBase: null });
		await expect(loaderFor(repo)("/repo")).rejects.toThrow("merge base");
	});

	test("propagates repository discovery failures", async () => {
		const load = createDiffLoader({
			openRepository: () => {
				throw new Error("not a repository");
			},
			env: {},
		});
		await expect(load("/nowhere")).rejects.toThrow("not a repository");
	});
});

describe("loadDiff untracked files", () => {
	test("appends untracked file patches in stable path order", async () => {
		const aPatch = "diff --git a/a.ts b/a.ts\nnew file mode 100644\n--- /dev/null\n+++ b/a.ts\n@@ -0,0 +1 @@\n+alpha\n";
		const zPatch = "diff --git a/z.ts b/z.ts\nnew file mode 100644\n--- /dev/null\n+++ b/z.ts\n@@ -0,0 +1 @@\n+zeta\n";
		const { repo, calls } = fakeRepo({ patch: "", untracked: { "z.ts": zPatch, "a.ts": aPatch } });

		const snapshot = await loaderFor(repo)("/repo");

		expect(calls.untrackedDiff).toEqual(["a.ts", "z.ts"]);
		expect(snapshot.patch).toBe(aPatch + zPatch);
		expect(snapshot.files.map((file) => file.path)).toEqual(["a.ts", "z.ts"]);
		expect(snapshot.files.map((file) => file.newLines.get(1))).toEqual(["alpha", "zeta"]);
	});
});

describe("loadDiff repository identity", () => {
	test("prefers BASECAMP_REPO for the repository name", async () => {
		const { repo } = fakeRepo();
		const snapshot = await loaderFor(repo, { BASECAMP_REPO: "acme/widgets" })("/repo");
		expect(snapshot.repository).toBe("acme/widgets");
	});

	test("falls back to the repository basename when BASECAMP_REPO is unset or blank", async () => {
		const unset = fakeRepo({ root: "/checkouts/widgets" });
		expect((await loaderFor(unset.repo)("/checkouts/widgets")).repository).toBe("widgets");

		const blank = fakeRepo({ root: "/checkouts/widgets" });
		expect((await loaderFor(blank.repo, { BASECAMP_REPO: "  " })("/checkouts/widgets")).repository).toBe("widgets");
	});
});

describe("loadDiff new-side range parsing", () => {
	test("parses hunk headers into inclusive 1-based new-side ranges", async () => {
		const { repo } = fakeRepo();
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([
			{
				path: "src/a.ts",
				newRanges: [{ start: 1, end: 3 }],
				newLines: new Map([
					[1, "context"],
					[2, "new"],
					[3, "added"],
				]),
			},
			{
				path: "src/b.ts",
				newRanges: [{ start: 10, end: 11 }],
				newLines: new Map([
					[10, "ctx"],
					[11, "more"],
				]),
			},
		]);
	});

	test("parses multiple hunks per file in order", async () => {
		const patch = [
			"diff --git a/f.ts b/f.ts",
			"--- a/f.ts",
			"+++ b/f.ts",
			"@@ -1 +1 @@",
			"-a",
			"+b",
			"@@ -20,3 +22,4 @@",
			" c",
			"+d",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([
			{
				path: "f.ts",
				newRanges: [
					{ start: 1, end: 1 },
					{ start: 22, end: 25 },
				],
				newLines: new Map([
					[1, "b"],
					[22, "c"],
					[23, "d"],
				]),
			},
		]);
	});

	test("pure-deletion hunks contribute no new-side range", async () => {
		const patch = [
			"diff --git a/f.ts b/f.ts",
			"--- a/f.ts",
			"+++ b/f.ts",
			"@@ -5,2 +4,0 @@",
			"-gone",
			"-also gone",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([{ path: "f.ts", newRanges: [], newLines: new Map() }]);
	});

	test("new files take their path from the +++ marker", async () => {
		const patch = [
			"diff --git a/added.ts b/added.ts",
			"new file mode 100644",
			"--- /dev/null",
			"+++ b/added.ts",
			"@@ -0,0 +1,2 @@",
			"+one",
			"+two",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([
			{
				path: "added.ts",
				newRanges: [{ start: 1, end: 2 }],
				newLines: new Map([
					[1, "one"],
					[2, "two"],
				]),
			},
		]);
	});

	test("deleted files take their path from the --- marker with no new-side ranges", async () => {
		const patch = [
			"diff --git a/gone.ts b/gone.ts",
			"deleted file mode 100644",
			"--- a/gone.ts",
			"+++ /dev/null",
			"@@ -1,2 +0,0 @@",
			"-one",
			"-two",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([{ path: "gone.ts", newRanges: [], newLines: new Map() }]);
	});

	test("decodes git's C-style quoted paths", async () => {
		const patch = [
			'diff --git "a/spa\\303\\247o.ts" "b/spa\\303\\247o.ts"',
			'--- "a/spa\\303\\247o.ts"',
			'+++ "b/spa\\303\\247o.ts"',
			"@@ -1 +1 @@",
			"-a",
			"+b",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([
			{ path: "spaço.ts", newRanges: [{ start: 1, end: 1 }], newLines: new Map([[1, "b"]]) },
		]);
	});

	test("added lines starting with ++ are not mistaken for markers", async () => {
		const patch = [
			"diff --git a/f.ts b/f.ts",
			"--- a/f.ts",
			"+++ b/f.ts",
			"@@ -1 +1,2 @@",
			" ctx",
			"+++ not a marker",
			"",
		].join("\n");
		const { repo } = fakeRepo({ patch });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files).toEqual([
			{
				path: "f.ts",
				newRanges: [{ start: 1, end: 2 }],
				newLines: new Map([
					[1, "ctx"],
					[2, "++ not a marker"],
				]),
			},
		]);
	});

	test("an empty patch yields no files", async () => {
		const { repo } = fakeRepo({ patch: "" });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.patch).toBe("");
		expect(snapshot.files).toEqual([]);
	});
});

describe("loadDiff path filters", () => {
	test("forwards validated paths to the diff, normalized", async () => {
		const { repo, calls } = fakeRepo();
		await loaderFor(repo)("/repo", { paths: ["./src/a.ts", "docs/"] });

		expect(calls.diffText).toEqual([{ base: "base-sha", files: ["src/a.ts", "docs"] }]);
		expect(calls.untrackedPaths).toEqual([["src/a.ts", "docs"]]);
	});

	test("an empty path list means the full diff", async () => {
		const { repo, calls } = fakeRepo();
		await loaderFor(repo)("/repo", { paths: [] });

		expect(calls.diffText).toEqual([{ base: "base-sha" }]);
		expect(calls.untrackedPaths).toEqual([[]]);
	});

	test("rejects path traversal", async () => {
		const { repo, calls } = fakeRepo();
		const load = loaderFor(repo);

		await expect(load("/repo", { paths: ["../outside.ts"] })).rejects.toThrow("escapes the repository");
		await expect(load("/repo", { paths: ["src/../../outside.ts"] })).rejects.toThrow("escapes the repository");
		await expect(load("/repo", { paths: ["..\\outside.ts"] })).rejects.toThrow("escapes the repository");
		expect(calls.diffText).toEqual([]);
	});

	test("rejects absolute, empty, and non-file paths", async () => {
		const { repo, calls } = fakeRepo();
		const load = loaderFor(repo);

		await expect(load("/repo", { paths: ["/etc/passwd"] })).rejects.toThrow("absolute");
		await expect(load("/repo", { paths: [""] })).rejects.toThrow("non-empty");
		await expect(load("/repo", { paths: ["./"] })).rejects.toThrow("does not name a path");
		expect(calls.diffText).toEqual([]);
	});
});
