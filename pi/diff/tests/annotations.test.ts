import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatAnnotations } from "#diff/annotations.ts";
import type { UserNote } from "#diff/hunk.ts";

describe("formatAnnotations", () => {
	it("collapses a single-line range and keeps a span", () => {
		const notes: UserNote[] = [
			{ filePath: "a.ts", newRange: [3, 3], body: "one line" },
			{ filePath: "b.ts", newRange: [12, 20], body: "a span" },
		];

		const text = formatAnnotations(notes);

		assert.match(text, /- a\.ts:3\n/);
		assert.match(text, /- b\.ts:12-20\n/);
	});

	it("anchors a note left on removed lines instead of degrading to the filename", () => {
		const notes: UserNote[] = [{ filePath: "gone.ts", oldRange: [8, 9], body: "why drop this?" }];

		assert.match(formatAnnotations(notes), /- gone\.ts:8-9 \(removed lines\)/);
	});

	it("falls back to the bare path when hunk anchors a note to no line at all", () => {
		assert.match(formatAnnotations([{ filePath: "whole.ts", body: "file-level" }]), /- whole\.ts\n/);
	});

	it("indents a multi-line body so it stays under its own bullet", () => {
		const text = formatAnnotations([{ filePath: "a.ts", newRange: [1, 1], body: "first\nsecond" }]);

		assert.match(text, /- a\.ts:1\n {2}first\n {2}second/);
	});

	it("uses singular wording for one annotation and plural beyond that", () => {
		const one = formatAnnotations([{ filePath: "a.ts", newRange: [1, 1], body: "x" }]);
		const two = formatAnnotations([
			{ filePath: "a.ts", newRange: [1, 1], body: "x" },
			{ filePath: "b.ts", newRange: [2, 2], body: "y" },
		]);

		assert.match(one, /left 1 annotation:/);
		assert.match(two, /left 2 annotations:/);
	});
});
