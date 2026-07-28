import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { Static } from "@sinclair/typebox";
import {
	AnnotatedFile,
	annotationId,
	clearSidecar,
	removeAnnotation,
	Sidecar,
	sidecarPath,
	writeSidecar,
} from "#diff/sidecar.ts";

function tmpScratch(t: TestContext): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "diff-sidecar-"));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	return dir;
}

function useScratch(t: TestContext): void {
	process.env.BASECAMP_SCRATCH_DIR = tmpScratch(t);
	t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
}

function readWritten(filePath: string): Static<typeof Sidecar> {
	return JSON.parse(fs.readFileSync(filePath, "utf8")) as Static<typeof Sidecar>;
}

function filePaths(sidecar: Static<typeof Sidecar>): string[] {
	return sidecar.files.map((f) => f.path);
}

/** One annotated file carrying a single annotation. */
function one(filePath: string, summary: string, newRange: [number, number] = [1, 1]): Static<typeof AnnotatedFile> {
	return { path: filePath, annotations: [{ newRange, summary }] };
}

describe("writeSidecar lifecycle", () => {
	it("merges — not overwrites — across two calls with the same base", (t) => {
		useScratch(t);

		const first = writeSidecar("/wt/merge", "abc1234", "First.", [one("a.ts", "first", [1, 5])]);
		const second = writeSidecar("/wt/merge", "abc1234", "Second.", [one("b.ts", "only", [1, 2])]);

		assert.equal(first.path, second.path);
		assert.equal(second.files, 2);
		assert.equal(second.annotations, 2);
		const written = readWritten(second.path);
		assert.equal(written.summary, "Second.");
		assert.deepEqual(filePaths(written), ["a.ts", "b.ts"]);
	});

	it("same-path merge appends annotations and replaces summaries", (t) => {
		useScratch(t);

		writeSidecar("/wt/samepath", "abc1234", "Top one.", [
			{ path: "a.ts", summary: "Old file summary.", annotations: [{ newRange: [1, 5], summary: "first" }] },
		]);
		const result = writeSidecar("/wt/samepath", "abc1234", "Top two.", [
			{ path: "a.ts", summary: "New file summary.", annotations: [{ newRange: [10, 20], summary: "second" }] },
		]);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 2);
		const written = readWritten(result.path);
		assert.equal(written.summary, "Top two.");
		assert.equal(written.files[0]?.summary, "New file summary.");
		assert.deepEqual(
			written.files[0]?.annotations.map((a) => a.summary),
			["first", "second"],
		);
	});

	it("collapses an exact duplicate submitted twice", (t) => {
		useScratch(t);

		const files = [one("a.ts", "same", [1, 5])];
		writeSidecar("/wt/dup", "abc1234", "One.", files);
		const result = writeSidecar("/wt/dup", "abc1234", "Two.", files);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 1);
	});

	it("stamps every written annotation with a 12-char hex id", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/ids", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "x" },
					{ newRange: [6, 7], summary: "y" },
				],
			},
		]);

		for (const f of readWritten(result.path).files) {
			for (const a of f.annotations) assert.match(a.id ?? "", /^[0-9a-f]{12}$/);
		}
	});

	it("a different base replaces the old span's files entirely", (t) => {
		useScratch(t);

		writeSidecar("/wt/span", "base-one", "Old span.", [one("old.ts", "stale", [1, 5])]);
		const result = writeSidecar("/wt/span", "base-two", "New span.", [one("new.ts", "fresh", [1, 2])]);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 1);
		const written = readWritten(result.path);
		assert.equal(written.basecampBase, "base-two");
		assert.equal(written.files[0]?.path, "new.ts");
	});

	it("overwrites an unparsable existing sidecar fresh, without throwing", (t) => {
		useScratch(t);
		const target = sidecarPath("/wt/torn-write");
		fs.mkdirSync(path.dirname(target), { recursive: true });
		fs.writeFileSync(target, '{"version":1,"basecampBase":"dead');

		const result = writeSidecar("/wt/torn-write", "abc1234", "S.", [one("a.ts", "x")]);

		const written = readWritten(result.path);
		assert.equal(written.basecampBase, "abc1234");
		assert.equal(written.files.length, 1);
	});
});

describe("annotationId", () => {
	it("is deterministic, summary-sensitive, and 12 hex chars", () => {
		assert.equal(annotationId("a.ts", [1, 5], "x"), annotationId("a.ts", [1, 5], "x"));
		assert.notEqual(annotationId("a.ts", [1, 5], "x"), annotationId("a.ts", [1, 5], "y"));
		assert.match(annotationId("a.ts", [1, 5], "x"), /^[0-9a-f]{12}$/);
	});
});

describe("clearSidecar", () => {
	it("removes the sidecar file, and clearing a missing file does not throw", (t) => {
		useScratch(t);
		const result = writeSidecar("/wt/clear", "abc1234", "S.", [one("a.ts", "x")]);
		assert.ok(fs.existsSync(result.path));

		clearSidecar("/wt/clear");

		assert.equal(fs.existsSync(result.path), false);
		assert.doesNotThrow(() => clearSidecar("/wt/never-written"));
	});
});

describe("removeAnnotation", () => {
	it("removes one annotation and rewrites the sidecar", (t) => {
		useScratch(t);
		const result = writeSidecar("/wt/rm", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "keep" },
					{ newRange: [6, 7], summary: "drop" },
				],
			},
		]);

		assert.deepEqual(removeAnnotation("/wt/rm", annotationId("a.ts", [6, 7], "drop")), { removed: true });

		const written = readWritten(result.path);
		assert.equal(written.files.length, 1);
		assert.deepEqual(
			written.files[0]?.annotations.map((a) => a.summary),
			["keep"],
		);
	});

	it("prunes a file entry when its last annotation is removed", (t) => {
		useScratch(t);
		const result = writeSidecar("/wt/rm-prune", "abc1234", "S.", [one("a.ts", "keep", [1, 5]), one("b.ts", "drop")]);

		assert.deepEqual(removeAnnotation("/wt/rm-prune", annotationId("b.ts", [1, 1], "drop")), { removed: true });

		assert.deepEqual(filePaths(readWritten(result.path)), ["a.ts"]);
	});

	it("deletes the sidecar file when the final annotation is removed", (t) => {
		useScratch(t);
		const result = writeSidecar("/wt/rm-last", "abc1234", "S.", [one("a.ts", "only", [1, 5])]);

		assert.deepEqual(removeAnnotation("/wt/rm-last", annotationId("a.ts", [1, 5], "only")), { removed: true });

		assert.equal(fs.existsSync(result.path), false);
	});

	it("reports an unknown key as not found, and no sidecar as no annotations", (t) => {
		useScratch(t);
		writeSidecar("/wt/rm-unknown", "abc1234", "S.", [one("a.ts", "x", [1, 5])]);

		const unknown = removeAnnotation("/wt/rm-unknown", "000000000000");
		assert.equal(unknown.removed, false);
		if (!unknown.removed) assert.match(unknown.reason, /not found/);

		const none = removeAnnotation("/wt/rm-none", "000000000000");
		assert.equal(none.removed, false);
		if (!none.removed) assert.match(none.reason, /no annotations recorded/);
	});

	it("does not resurrect a removed annotation on a later merge", (t) => {
		useScratch(t);
		const result = writeSidecar("/wt/rm-merge", "abc1234", "A.", [one("a.ts", "gone", [1, 5])]);
		removeAnnotation("/wt/rm-merge", annotationId("a.ts", [1, 5], "gone"));
		assert.equal(fs.existsSync(result.path), false);

		const second = writeSidecar("/wt/rm-merge", "abc1234", "B.", [one("b.ts", "here", [1, 2])]);

		const written = readWritten(second.path);
		assert.deepEqual(filePaths(written), ["b.ts"]);
		assert.equal(written.files[0]?.annotations.length, 1);
	});
});
