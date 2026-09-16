import { describe, expect, test } from "bun:test";
import { parseUntrackedPorcelain, relabelNoIndexPatch } from "../untracked.ts";
import { fakeRepo, loaderFor } from "./support/loader-harness.ts";

const ADDITION = [
	"diff --git a/new.ts b/new.ts",
	"new file mode 100644",
	"--- /dev/null",
	"+++ b/new.ts",
	"@@ -0,0 +1 @@",
	"+export const value = 1;",
	"",
].join("\n");

const DELETION = [
	"diff --git a/new.ts b/new.ts",
	"deleted file mode 100644",
	"--- a/new.ts",
	"+++ /dev/null",
	"@@ -1 +0,0 @@",
	"-export const old = 1;",
	"",
].join("\n");

describe("untracked diff loading", () => {
	test("consumes the extra source field of rename and copy records", () => {
		expect(parseUntrackedPorcelain("R  renamed.ts\0?? source-looking.ts\0?? actual.ts\0")).toEqual(["actual.ts"]);
	});

	test("uses repository-relative labels even when no-index receives an absolute path", () => {
		const absolute = [
			"diff --git a/dev/null b/Users/example/repo/NUL",
			"--- /dev/null",
			"+++ b/Users/example/repo/NUL",
			"@@ -0,0 +1 @@",
			"+--- payload text",
			"",
		].join("\n");
		const patch = relabelNoIndexPatch(absolute, "NUL");

		expect(patch).toContain("diff --git a/NUL b/NUL");
		expect(patch).toContain("+++ b/NUL");
		expect(patch).toContain("--- /dev/null");
		expect(patch).toContain("+--- payload text");
		expect(patch).not.toContain("/Users/example/repo");
	});

	test("reports an untracked directory while retaining ordinary untracked files", async () => {
		const { repo } = fakeRepo({
			patch: "",
			untracked: { "vendor/nested/": null, "new.ts": ADDITION },
		});
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files.map((file) => file.path)).toEqual(["new.ts"]);
		expect(snapshot.warnings).toEqual([
			'Untracked directory "vendor/nested/" was omitted; embedded repositories are not expanded.',
		]);
	});

	test("reports a disappearing untracked file while retaining the remaining diff", async () => {
		const { repo } = fakeRepo({
			patch: "",
			untracked: { "gone.ts": new Error("ENOENT"), "new.ts": ADDITION },
		});
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.files.map((file) => file.path)).toEqual(["new.ts"]);
		expect(snapshot.warnings).toEqual(['Untracked path "gone.ts" was omitted because it could not be read: ENOENT']);
	});

	test("propagates cancellation instead of degrading it to an omission warning", async () => {
		const cancelled = Object.assign(new Error("cancelled"), { code: "Canceled" });
		const { repo } = fakeRepo({ patch: "", untracked: { "new.ts": cancelled } });

		await expect(loaderFor(repo)("/repo")).rejects.toThrow("cancelled");
	});
	test("coalesces a tracked deletion and same-path untracked file into the working-tree addition", async () => {
		const { repo } = fakeRepo({ patch: DELETION, untracked: { "new.ts": ADDITION } });
		const snapshot = await loaderFor(repo)("/repo");

		expect(snapshot.patch.match(/^diff --git /gm)).toHaveLength(1);
		expect(snapshot.patch).toContain("new file mode 100644");
		expect(snapshot.patch).not.toContain("deleted file mode");
		expect(snapshot.files).toHaveLength(1);
		expect(snapshot.files[0]?.newLines.get(1)).toBe("export const value = 1;");
	});
});
