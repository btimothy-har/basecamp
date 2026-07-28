import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import { type Static, type TSchema } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import {
	AnnotatedFile,
	Annotation,
	PRIVATE_DIR_MODE,
	PRIVATE_FILE_MODE,
	readSidecarBase,
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

/** One annotated file carrying a single annotation. */
function one(filePath: string, summary: string, newRange: [number, number] = [1, 1]): Static<typeof AnnotatedFile> {
	return { path: filePath, annotations: [{ newRange, summary }] };
}

function validSidecar(): Static<typeof Sidecar> {
	return {
		version: 1,
		basecampBase: "abc1234",
		summary: "Changeset summary.",
		files: [
			{
				path: "pi/diff/sidecar.ts",
				summary: "Sidecar writer.",
				annotations: [
					{ newRange: [5, 47], summary: "Writer core", rationale: "Mirrors artifact.ts." },
					{ newRange: [50, 60], summary: "Path derivation" },
				],
			},
		],
	};
}

function check(value: unknown, schema: TSchema): boolean {
	return Value.Check(schema, value);
}

describe("sidecar schema", () => {
	it("accepts a well-formed sidecar, with optionals omitted", () => {
		assert.equal(check(validSidecar(), Sidecar), true);
		const s = validSidecar();
		s.files[0]!.summary = undefined;
		s.files[0]!.annotations = [{ newRange: [1, 1], summary: "only a summary" }];
		assert.equal(check(s, Sidecar), true);
	});

	it("rejects empty summaries, extra keys, wrong version, and non-integer ranges", () => {
		const emptyTop = validSidecar();
		emptyTop.summary = "";
		assert.equal(check(emptyTop, Sidecar), false);

		const emptyAnnotation = validSidecar();
		emptyAnnotation.files[0]!.annotations[0]!.summary = "";
		assert.equal(check(emptyAnnotation, Sidecar), false);

		const a: Static<typeof Annotation> = { newRange: [1, 2], summary: "x", rationale: "y" };
		assert.equal(check({ ...a, extra: true }, Annotation), false);
		const f: Static<typeof AnnotatedFile> = { path: "a.ts", annotations: [] };
		assert.equal(check({ ...f, extra: true }, AnnotatedFile), false);

		const wrongVersion = validSidecar();
		(wrongVersion as { version: number }).version = 2;
		assert.equal(check(wrongVersion, Sidecar), false);

		const fractional = validSidecar();
		(fractional.files[0]!.annotations[0] as { newRange: [number, number] }).newRange = [1.5, 2];
		assert.equal(check(fractional, Sidecar), false);
	});
});

describe("sidecarPath", () => {
	it("is stable per worktree, distinct across worktrees, and honors BASECAMP_SCRATCH_DIR", (t) => {
		assert.equal(sidecarPath("/wt/same"), sidecarPath("/wt/same"));
		assert.notEqual(sidecarPath("/wt/alpha"), sidecarPath("/wt/beta"));
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		assert.ok(sidecarPath("/wt/x").startsWith(scratch));
	});
});

describe("writeSidecar", () => {
	it("writes a valid JSON sidecar with 0600 mode", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/test", "abc1234", "Summary.", [one("a.ts", "head", [1, 5])]);

		assert.equal(fs.statSync(result.path).mode & 0o777, PRIVATE_FILE_MODE);
		const written = readWritten(result.path);
		assert.equal(written.version, 1);
		assert.equal(written.summary, "Summary.");
		assert.equal(written.files.length, 1);
		assert.equal(written.files[0]?.path, "a.ts");
	});

	it("counts files and annotations in the result", (t) => {
		useScratch(t);

		const result = writeSidecar("/wt/count", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "x" },
					{ newRange: [6, 7], summary: "y" },
				],
			},
			one("b.ts", "z"),
		]);

		assert.equal(result.files, 2);
		assert.equal(result.annotations, 3);
	});

	it("writes the diff directory 0700, tightening a looser pre-existing one", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		writeSidecar("/wt/dir", "abc1234", "S.", [one("a.ts", "x")]);
		assert.equal(fs.statSync(path.join(scratch, "diff")).mode & 0o777, PRIVATE_DIR_MODE);

		// The chmod only earns its place when the directory pre-exists.
		const target = sidecarPath("/wt/loose");
		fs.chmodSync(path.dirname(target), 0o755);
		fs.writeFileSync(target, "{}");
		fs.chmodSync(target, 0o644);
		writeSidecar("/wt/loose", "abc1234", "S.", [one("a.ts", "x")]);
		assert.equal(fs.statSync(path.dirname(target)).mode & 0o777, PRIVATE_DIR_MODE);
		assert.equal(fs.statSync(target).mode & 0o777, PRIVATE_FILE_MODE);
	});

	it("two worktrees write to distinct files, with no scratch files left beside them", (t) => {
		useScratch(t);

		const a = writeSidecar("/wt/alpha", "abc1234", "A.", [one("a.ts", "x")]);
		const b = writeSidecar("/wt/beta", "abc1234", "B.", [one("b.ts", "y")]);

		assert.notEqual(a.path, b.path);
		const siblings = fs.readdirSync(path.dirname(a.path)).sort();
		assert.deepEqual(siblings, [path.basename(a.path), path.basename(b.path)].sort());
	});
});

describe("readSidecarBase", () => {
	it("returns null when no sidecar has been written", (t) => {
		useScratch(t);
		assert.equal(readSidecarBase("/wt/none"), null);
	});

	it("round-trips the base a sidecar was written against", (t) => {
		useScratch(t);
		writeSidecar("/wt/stamp", "deadbeef", "S.", [one("a.ts", "x")]);
		assert.equal(readSidecarBase("/wt/stamp"), "deadbeef");
	});

	it("returns null for a torn or unparsable sidecar rather than throwing", (t) => {
		useScratch(t);
		const target = sidecarPath("/wt/torn");
		fs.mkdirSync(path.dirname(target), { recursive: true });
		fs.writeFileSync(target, '{"version":1,"basecampBase":"dead');
		assert.equal(readSidecarBase("/wt/torn"), null);
	});
});
