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
	it("accepts a well-formed sidecar", () => {
		assert.equal(check(validSidecar(), Sidecar), true);
	});

	it("accepts a file without optional per-file summary", () => {
		const s = validSidecar();
		s.files[0]!.summary = undefined;
		assert.equal(check(s, Sidecar), true);
	});

	it("accepts an annotation without optional rationale", () => {
		assert.equal(check(validSidecar(), Sidecar), true);
	});

	it("rejects an empty top-level summary", () => {
		const s = validSidecar();
		s.summary = "";
		assert.equal(check(s, Sidecar), false);
	});

	it("rejects an empty annotation summary", () => {
		const s = validSidecar();
		s.files[0]!.annotations[0]!.summary = "";
		assert.equal(check(s, Sidecar), false);
	});

	it("rejects additionalProperties on an annotation", () => {
		const a: Static<typeof Annotation> = {
			newRange: [1, 2],
			summary: "x",
			rationale: "y",
		};
		const bad = { ...a, extra: true };
		assert.equal(check(bad, Annotation), false);
	});

	it("rejects additionalProperties on a file", () => {
		const f: Static<typeof AnnotatedFile> = {
			path: "a.ts",
			annotations: [],
		};
		const bad = { ...f, extra: true };
		assert.equal(check(bad, AnnotatedFile), false);
	});

	it("rejects version other than 1", () => {
		const s = validSidecar();
		(s as { version: number }).version = 2;
		assert.equal(check(s, Sidecar), false);
	});

	it("rejects non-integer range values", () => {
		const s = validSidecar();
		(s.files[0]!.annotations[0] as { newRange: [number, number] }).newRange = [1.5, 2];
		assert.equal(check(s, Sidecar), false);
	});
});

describe("sidecarPath", () => {
	it("produces distinct paths for distinct worktree dirs", () => {
		const a = sidecarPath("/wt/alpha");
		const b = sidecarPath("/wt/beta");
		assert.notEqual(a, b);
	});

	it("is stable for the same worktree dir", () => {
		assert.equal(sidecarPath("/wt/same"), sidecarPath("/wt/same"));
	});

	it("resolves under BASECAMP_SCRATCH_DIR when set", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		const p = sidecarPath("/wt/x");
		assert.ok(p.startsWith(scratch));
	});
});

describe("writeSidecar", () => {
	it("writes a valid JSON sidecar with 0600 mode", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		const result = writeSidecar("/wt/test", "abc1234", "Summary.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 5], summary: "head" }] },
		]);

		const stat = fs.statSync(result.path);
		const mode = stat.mode & 0o777;
		assert.equal(mode, PRIVATE_FILE_MODE);

		const written = JSON.parse(fs.readFileSync(result.path, "utf8")) as Static<typeof Sidecar>;
		assert.equal(written.version, 1);
		assert.equal(written.summary, "Summary.");
		assert.equal(written.files.length, 1);
		assert.equal(written.files[0]?.path, "a.ts");
	});

	it("overwrites — not appends — across two calls", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		const first = writeSidecar("/wt/ow", "abc1234", "First.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "first" },
					{ newRange: [10, 20], summary: "second" },
				],
			},
		]);
		const second = writeSidecar("/wt/ow", "abc1234", "Second.", [
			{ path: "b.ts", annotations: [{ newRange: [1, 2], summary: "only" }] },
		]);

		assert.equal(first.path, second.path);
		const written = JSON.parse(fs.readFileSync(second.path, "utf8")) as Static<typeof Sidecar>;
		assert.equal(written.summary, "Second.");
		assert.equal(written.files.length, 1);
		assert.equal(written.files[0]?.path, "b.ts");
		assert.equal(written.files[0]?.annotations.length, 1);
	});

	it("counts files and annotations in the result", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		const result = writeSidecar("/wt/count", "abc1234", "S.", [
			{
				path: "a.ts",
				annotations: [
					{ newRange: [1, 5], summary: "x" },
					{ newRange: [6, 7], summary: "y" },
				],
			},
			{ path: "b.ts", annotations: [{ newRange: [1, 1], summary: "z" }] },
		]);

		assert.equal(result.files, 2);
		assert.equal(result.annotations, 3);
	});

	it("creates the diff directory with 0700 mode", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		writeSidecar("/wt/dir", "abc1234", "S.", [{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] }]);

		const dir = path.join(scratch, "diff");
		const mode = fs.statSync(dir).mode & 0o777;
		assert.equal(mode, PRIVATE_DIR_MODE);
	});

	it("two worktrees write to distinct files", (t) => {
		const scratch = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = scratch;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);

		const a = writeSidecar("/wt/alpha", "abc1234", "A.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] },
		]);
		const b = writeSidecar("/wt/beta", "abc1234", "B.", [
			{ path: "b.ts", annotations: [{ newRange: [1, 1], summary: "y" }] },
		]);

		assert.notEqual(a.path, b.path);
		assert.ok(fs.existsSync(a.path));
		assert.ok(fs.existsSync(b.path));
	});
});

describe("readSidecarBase", () => {
	it("returns null when no sidecar has been written", (t) => {
		const dir = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = dir;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		assert.equal(readSidecarBase("/wt/none"), null);
	});

	it("round-trips the base a sidecar was written against", (t) => {
		const dir = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = dir;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		writeSidecar("/wt/stamp", "deadbeef", "S.", [{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] }]);
		assert.equal(readSidecarBase("/wt/stamp"), "deadbeef");
	});

	it("returns null for a torn or unparsable sidecar rather than throwing", (t) => {
		const dir = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = dir;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		const target = sidecarPath("/wt/torn");
		fs.mkdirSync(path.dirname(target), { recursive: true });
		fs.writeFileSync(target, '{"version":1,"basecampBase":"dead');
		assert.equal(readSidecarBase("/wt/torn"), null);
	});

	it("leaves no temp file behind, so a rename-based write is invisible to callers", (t) => {
		const dir = tmpScratch(t);
		process.env.BASECAMP_SCRATCH_DIR = dir;
		t.after(() => delete process.env.BASECAMP_SCRATCH_DIR);
		const result = writeSidecar("/wt/atomic", "abc1234", "S.", [
			{ path: "a.ts", annotations: [{ newRange: [1, 1], summary: "x" }] },
		]);
		const siblings = fs.readdirSync(path.dirname(result.path));
		assert.deepEqual(siblings, [path.basename(result.path)]);
	});
});
