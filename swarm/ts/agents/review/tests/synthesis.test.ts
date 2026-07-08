import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Finding } from "../findings.ts";
import { computeVerdict, mergeFindings } from "../synthesis.ts";

function finding(overrides: Partial<Finding>): Finding {
	return {
		dimension: "general",
		severity: "low",
		file: null,
		lineStart: null,
		lineEnd: null,
		title: "finding",
		detail: "detail",
		remediation: null,
		...overrides,
	};
}

describe("mergeFindings", () => {
	it("returns an empty array for empty report inputs", () => {
		assert.deepEqual(mergeFindings([]), []);
		assert.deepEqual(mergeFindings([[], []]), []);
	});

	it("orders by severity, file, and line with nulls last while preserving duplicates", () => {
		const duplicate = finding({ severity: "high", file: "a.ts", lineStart: 2, title: "duplicate" });
		const duplicateCopy = finding({ severity: "high", file: "a.ts", lineStart: 2, title: "duplicate" });
		const merged = mergeFindings([
			[
				finding({ severity: "low", file: null, lineStart: null, title: "low-null-file" }),
				finding({ severity: "high", file: "b.ts", lineStart: null, title: "high-b-null-line" }),
				duplicate,
				finding({ severity: "critical", file: null, lineStart: null, title: "critical-null-file" }),
			],
			[
				finding({ severity: "high", file: "a.ts", lineStart: null, title: "high-a-null-line" }),
				finding({ severity: "medium", file: "m.ts", lineStart: 1, title: "medium" }),
				duplicateCopy,
				finding({ severity: "high", file: "a.ts", lineStart: 10, title: "high-a-line-10" }),
			],
		]);

		assert.deepEqual(
			merged.map((item) => item.title),
			[
				"critical-null-file",
				"duplicate",
				"duplicate",
				"high-a-line-10",
				"high-a-null-line",
				"high-b-null-line",
				"medium",
				"low-null-file",
			],
		);
		assert.equal(merged[1], duplicate);
		assert.equal(merged[2], duplicateCopy);
	});
});

describe("computeVerdict", () => {
	it("requests changes and blocks for critical findings", () => {
		assert.deepEqual(computeVerdict([finding({ severity: "critical" })]), {
			decision: "request-changes",
			blocking: true,
			counts: { critical: 1, high: 0, medium: 0, low: 0 },
		});
	});

	it("requests changes and blocks for three or more high findings", () => {
		assert.deepEqual(
			computeVerdict([
				finding({ severity: "high" }),
				finding({ severity: "high" }),
				finding({ severity: "high" }),
				finding({ severity: "low" }),
			]),
			{
				decision: "request-changes",
				blocking: true,
				counts: { critical: 0, high: 3, medium: 0, low: 1 },
			},
		);
	});

	it("comments without blocking for one or two high findings", () => {
		assert.deepEqual(computeVerdict([finding({ severity: "high" }), finding({ severity: "medium" })]), {
			decision: "comment",
			blocking: false,
			counts: { critical: 0, high: 1, medium: 1, low: 0 },
		});
	});

	it("comments without blocking for exactly two high findings", () => {
		assert.deepEqual(computeVerdict([finding({ severity: "high" }), finding({ severity: "high" })]), {
			decision: "comment",
			blocking: false,
			counts: { critical: 0, high: 2, medium: 0, low: 0 },
		});
	});

	it("approves with notes for only medium and low findings", () => {
		assert.deepEqual(computeVerdict([finding({ severity: "medium" }), finding({ severity: "low" })]), {
			decision: "approve-with-notes",
			blocking: false,
			counts: { critical: 0, high: 0, medium: 1, low: 1 },
		});
	});

	it("approves cleanly when there are no findings", () => {
		assert.deepEqual(computeVerdict([]), {
			decision: "approve",
			blocking: false,
			counts: { critical: 0, high: 0, medium: 0, low: 0 },
		});
	});
});
