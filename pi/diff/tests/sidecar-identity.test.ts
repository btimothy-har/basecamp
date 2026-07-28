import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { Static } from "@sinclair/typebox";
import { AnnotatedFile, annotationId, removeAnnotation, Sidecar, writeSidecar } from "#diff/sidecar.ts";

function tmpScratch(t: TestContext): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "diff-identity-"));
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

/** One annotated file carrying a single annotation. */
function one(filePath: string, summary: string, newRange: [number, number] = [1, 1]): Static<typeof AnnotatedFile> {
	return { path: filePath, annotations: [{ newRange, summary }] };
}

describe("annotationId", () => {
	it("is deterministic, summary-sensitive, and 12 hex chars", () => {
		assert.equal(annotationId("a.ts", [1, 5], "x"), annotationId("a.ts", [1, 5], "x"));
		assert.notEqual(annotationId("a.ts", [1, 5], "x"), annotationId("a.ts", [1, 5], "y"));
		assert.match(annotationId("a.ts", [1, 5], "x"), /^[0-9a-f]{12}$/);
	});

	it("changes when only the rationale differs, stable when all four inputs match", () => {
		assert.equal(annotationId("a.ts", [1, 5], "x", "because"), annotationId("a.ts", [1, 5], "x", "because"));
		assert.notEqual(annotationId("a.ts", [1, 5], "x", "old"), annotationId("a.ts", [1, 5], "x", "new"));
		assert.notEqual(annotationId("a.ts", [1, 5], "x"), annotationId("a.ts", [1, 5], "x", "new"));
	});
});

describe("rationale supersession", () => {
	it("a corrected rationale replaces the stored one in place, keeping the count at 1", (t) => {
		useScratch(t);

		writeSidecar("/wt/reword", "abc1234", "One.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 5], summary: "same", rationale: "OLD wrong text" }] },
		]);
		const second = writeSidecar("/wt/reword", "abc1234", "Two.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 5], summary: "same", rationale: "NEW corrected text" }] },
		]);

		const newId = annotationId("a.ts", [1, 5], "same", "NEW corrected text");
		assert.equal(second.files, 1);
		assert.equal(second.annotations, 1); // Replaced in place — not appended.
		const stored = readWritten(second.path).files[0]?.annotations;
		assert.equal(stored?.length, 1);
		assert.equal(stored?.[0]?.rationale, "NEW corrected text");
		assert.equal(stored?.[0]?.id, newId);
		// The superseding annotation is reported as this call's contribution.
		assert.deepEqual(second.recorded, [{ id: newId, path: "a.ts", newRange: [1, 5], summary: "same" }]);
		// And the corrected annotation stays withdrawable by its new key.
		assert.deepEqual(removeAnnotation("/wt/reword", newId), { removed: true });
	});

	it("supersedes within a single call on a fresh span, not only against a stored sidecar", (t) => {
		// The guarantee must not depend on whether a sidecar for this span exists:
		// the first call of a span took a different path and kept both rationales,
		// so hunk rendered two annotations on one anchor and the tool reported both
		// keys as independently meaningful.
		useScratch(t);

		const result = writeSidecar("/wt/fresh-supersede", "abc1234", "One.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "same", rationale: "first pass" },
					{ newRange: [1, 5], summary: "same", rationale: "corrected" },
				],
			},
		]);

		assert.equal(result.annotations, 1);
		const stored = readWritten(result.path).files[0]?.annotations;
		assert.equal(stored?.length, 1);
		assert.equal(stored?.[0]?.rationale, "corrected");
		assert.deepEqual(result.recorded, [
			{ id: annotationId("a.ts", [1, 5], "same", "corrected"), path: "a.ts", newRange: [1, 5], summary: "same" },
		]);
	});

	it("an exact duplicate, rationale included, still collapses", (t) => {
		useScratch(t);
		const files = [
			{
				path: "a.ts",
				annotations: [{ newRange: [1, 5] as [number, number], summary: "same", rationale: "identical" }],
			},
		];
		writeSidecar("/wt/dup-rationale", "abc1234", "One.", files);

		const result = writeSidecar("/wt/dup-rationale", "abc1234", "Two.", files);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 1);
		assert.deepEqual(result.recorded, []);
	});
});

describe("same-path coalescing", () => {
	it("two entries for one path in one call fold into a single file entry", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/coalesce", "abc1234", "S.", [
			{ path: "a.ts", summary: "Earlier file summary.", annotations: [{ newRange: [1, 5], summary: "first" }] },
			{ path: "a.ts", summary: "Later file summary.", annotations: [{ newRange: [6, 7], summary: "second" }] },
		]);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 2);
		const written = readWritten(result.path);
		assert.equal(written.files.length, 1);
		assert.equal(written.files[0]?.summary, "Later file summary.");
		assert.deepEqual(
			written.files[0]?.annotations.map((a) => a.summary),
			["first", "second"],
		);
	});

	it("coalescing keeps the within-batch exact-duplicate collapse across entries", (t) => {
		useScratch(t);
		const entry = { path: "a.ts", annotations: [{ newRange: [1, 5] as [number, number], summary: "only" }] };

		const result = writeSidecar("/wt/coalesce-dup", "abc1234", "S.", [entry, entry]);

		assert.equal(result.files, 1);
		assert.equal(result.annotations, 1);
		assert.equal(result.recorded.length, 1);
	});

	it("after coalescing, removeAnnotation withdraws either annotation without ambiguity", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/coalesce-rm", "abc1234", "S.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 5], summary: "first" }] },
			{ path: "a.ts", annotations: [{ newRange: [6, 7], summary: "second" }] },
		]);

		assert.deepEqual(removeAnnotation("/wt/coalesce-rm", annotationId("a.ts", [1, 5], "first")), { removed: true });
		assert.deepEqual(removeAnnotation("/wt/coalesce-rm", annotationId("a.ts", [6, 7], "second")), { removed: true });
		assert.equal(fs.existsSync(result.path), false);
	});
});

describe("WriteResult.recorded", () => {
	it("lists exactly this call's contributions, with stamped ids, in call order", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/recorded", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "x" },
					{ newRange: [6, 7], summary: "y", rationale: "why" },
				],
			},
			one("b.ts", "z"),
		]);

		assert.deepEqual(result.recorded, [
			{ id: annotationId("a.ts", [1, 5], "x"), path: "a.ts", newRange: [1, 5], summary: "x" },
			{ id: annotationId("a.ts", [6, 7], "y", "why"), path: "a.ts", newRange: [6, 7], summary: "y" },
			{ id: annotationId("b.ts", [1, 1], "z"), path: "b.ts", newRange: [1, 1], summary: "z" },
		]);
	});
});
