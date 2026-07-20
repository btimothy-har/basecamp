import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import { isRecord, readJsonFile, writeJsonFileAtomic } from "../files.ts";
import { isStrictlyWithin, isWithin } from "../paths.ts";

describe("isRecord", () => {
	it("accepts plain objects and rejects null, arrays, and primitives", () => {
		assert.equal(isRecord({}), true);
		assert.equal(isRecord({ a: 1 }), true);
		assert.equal(isRecord(null), false);
		assert.equal(isRecord([]), false);
		assert.equal(isRecord("x"), false);
		assert.equal(isRecord(3), false);
		assert.equal(isRecord(undefined), false);
	});
});

describe("writeJsonFileAtomic + readJsonFile", () => {
	it("round-trips a value, creating missing parent directories", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bc-files-"));
		try {
			const file = path.join(dir, "nested", "data.json");
			const value = { a: 1, b: ["x", "y"], c: { d: true } };
			writeJsonFileAtomic(file, value);
			assert.deepEqual(readJsonFile(file), value);
			assert.equal(fs.existsSync(`${file}.tmp`), false);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});

	it("readJsonFile returns null for a missing file", () => {
		assert.equal(readJsonFile(path.join(os.tmpdir(), "bc-missing-4f1c9a.json")), null);
	});

	it("readJsonFile returns null for malformed JSON", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "bc-files-"));
		try {
			const file = path.join(dir, "bad.json");
			fs.writeFileSync(file, "{not json");
			assert.equal(readJsonFile(file), null);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("isWithin / isStrictlyWithin", () => {
	it("isWithin includes the equal-path case; isStrictlyWithin excludes it", () => {
		const parent = path.join(os.tmpdir(), "root");
		assert.equal(isWithin(parent, parent), true);
		assert.equal(isStrictlyWithin(parent, parent), false);
	});

	it("accepts nested children and rejects siblings, parents, and outside paths", () => {
		assert.equal(isWithin("/a/b/c", "/a/b"), true);
		assert.equal(isStrictlyWithin("/a/b/c", "/a/b"), true);
		assert.equal(isWithin("/a/x", "/a/b"), false);
		assert.equal(isStrictlyWithin("/a/x", "/a/b"), false);
		assert.equal(isWithin("/a", "/a/b"), false);
	});

	it("takes arguments in (child, parent) order", () => {
		assert.equal(isWithin("/a/b/c", "/a/b"), true);
		assert.equal(isWithin("/a/b", "/a/b/c"), false);
	});
});
