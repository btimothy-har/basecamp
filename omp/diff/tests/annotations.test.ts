import { describe, expect, test } from "bun:test";
import { anchorHash, annotationId, contentLines, span } from "../annotations.ts";

const base = {
	repository: "basecamp",
	path: "src/a.ts",
	newRange: { start: 2, end: 4 },
	summary: "watch this",
};

describe("annotationId", () => {
	test("is deterministic for identical content", () => {
		expect(annotationId(base)).toBe(annotationId({ ...base }));
	});

	test("is a 12-character lowercase hex string", () => {
		expect(annotationId(base)).toMatch(/^[0-9a-f]{12}$/);
	});

	test("changes with repository, path, range, and summary", () => {
		const id = annotationId(base);
		expect(annotationId({ ...base, repository: "other" })).not.toBe(id);
		expect(annotationId({ ...base, path: "src/b.ts" })).not.toBe(id);
		expect(annotationId({ ...base, newRange: { start: 3, end: 4 } })).not.toBe(id);
		expect(annotationId({ ...base, newRange: { start: 2, end: 5 } })).not.toBe(id);
		expect(annotationId({ ...base, summary: "reworded" })).not.toBe(id);
	});

	test("a corrected rationale yields a new key, so rewording never collides", () => {
		expect(annotationId({ ...base, rationale: "v2" })).not.toBe(annotationId({ ...base, rationale: "v1" }));
	});

	test("treats an omitted rationale and an empty one identically", () => {
		expect(annotationId(base)).toBe(annotationId({ ...base, rationale: "" }));
	});
});

describe("contentLines", () => {
	test("splits LF content and drops the trailing-newline artifact", () => {
		expect(contentLines("one\ntwo\nthree\n")).toEqual(["one", "two", "three"]);
		expect(contentLines("one")).toEqual(["one"]);
	});

	test("keeps interior empty lines", () => {
		expect(contentLines("one\n\nthree\n")).toEqual(["one", "", "three"]);
	});

	test("normalizes CRLF", () => {
		expect(contentLines("one\r\ntwo\r\n")).toEqual(["one", "two"]);
	});

	test("an empty file has no lines", () => {
		expect(contentLines("")).toEqual([]);
	});
});

describe("anchorHash", () => {
	const content = "one\ntwo\nthree\nfour\nfive\n";

	test("is stable for the same path, range, and content", () => {
		expect(anchorHash("src/a.ts", { start: 2, end: 4 }, content)).toBe(
			anchorHash("src/a.ts", { start: 2, end: 4 }, content),
		);
	});

	test("an edit inside the range changes the hash", () => {
		const original = anchorHash("src/a.ts", { start: 2, end: 4 }, content);
		expect(anchorHash("src/a.ts", { start: 2, end: 4 }, "one\nTWO\nthree\nfour\nfive\n")).not.toBe(original);
	});

	test("an edit outside the range keeps the hash", () => {
		const original = anchorHash("src/a.ts", { start: 2, end: 4 }, content);
		expect(anchorHash("src/a.ts", { start: 2, end: 4 }, "ZERO\ntwo\nthree\nfour\nfive\n")).toBe(original);
	});

	test("a line inserted above the range shifts the excerpt and changes the hash", () => {
		const original = anchorHash("src/a.ts", { start: 2, end: 4 }, content);
		expect(anchorHash("src/a.ts", { start: 2, end: 4 }, "new\none\ntwo\nthree\nfour\nfive\n")).not.toBe(original);
	});

	test("path and range are part of the hash", () => {
		const original = anchorHash("src/a.ts", { start: 2, end: 4 }, content);
		expect(anchorHash("src/b.ts", { start: 2, end: 4 }, content)).not.toBe(original);
		expect(anchorHash("src/a.ts", { start: 2, end: 3 }, content)).not.toBe(original);
	});

	test("CRLF and LF line endings hash identically", () => {
		expect(anchorHash("src/a.ts", { start: 1, end: 2 }, "one\r\ntwo\r\n")).toBe(
			anchorHash("src/a.ts", { start: 1, end: 2 }, "one\ntwo\n"),
		);
	});

	test("returns null for ranges that cannot address the content", () => {
		expect(anchorHash("src/a.ts", { start: 0, end: 2 }, content)).toBeNull();
		expect(anchorHash("src/a.ts", { start: 4, end: 2 }, content)).toBeNull();
		expect(anchorHash("src/a.ts", { start: 1, end: 6 }, content)).toBeNull();
		expect(anchorHash("src/a.ts", { start: 1.5, end: 2 }, content)).toBeNull();
	});
});

describe("span", () => {
	test("renders a single line and a range", () => {
		expect(span({ start: 12, end: 12 })).toBe("12");
		expect(span({ start: 12, end: 20 })).toBe("12-20");
	});
});
