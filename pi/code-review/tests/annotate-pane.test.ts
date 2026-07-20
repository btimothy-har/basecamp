import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildReactions, findingSummaryLines, responseDisplayLines } from "../annotate-pane.ts";
import type { Finding } from "../findings.ts";

function finding(overrides: Partial<Finding>): Finding {
	return {
		dimension: "general",
		severity: "low",
		file: null,
		lineStart: null,
		lineEnd: null,
		title: "Finding title",
		detail: "Finding detail",
		remediation: null,
		...overrides,
	};
}

describe("buildReactions", () => {
	it("returns trimmed reactions aligned to findings by index", () => {
		const findings = [
			finding({ title: "first" }),
			finding({ title: "second" }),
			finding({ title: "third" }),
			finding({ title: "fourth" }),
		];
		const drafts = new Map<number, string>([
			[0, "  intentional  "],
			[1, "   "],
			[2, "question about this"],
		]);

		const reactions = buildReactions(findings, drafts);

		assert.equal(reactions.length, findings.length);
		assert.deepEqual(reactions, ["intentional", null, "question about this", null]);
	});
});

describe("findingSummaryLines", () => {
	it("summarizes fileless findings with unknown line and missing remediation", () => {
		const lines = findingSummaryLines(
			finding({
				dimension: "security",
				severity: "high",
				file: null,
				lineStart: null,
				title: "Secret can leak",
				detail: "Token is logged.",
				remediation: null,
			}),
			0,
			3,
		);

		assert.ok(lines.includes("Finding 1 of 3"));
		assert.ok(lines.includes("[high] [security]  (no file):?"));
		assert.ok(lines.includes("Secret can leak"));
		assert.ok(lines.includes("Fix: —"));
	});

	it("summarizes findings with file, line, and remediation text", () => {
		const lines = findingSummaryLines(
			finding({
				dimension: "testing",
				severity: "medium",
				file: "src/app.ts",
				lineStart: 42,
				title: "Missing regression coverage",
				detail: "The edge case is untested.",
				remediation: "Add a regression test.",
			}),
			1,
			2,
		);

		assert.ok(lines.includes("Finding 2 of 2"));
		assert.ok(lines.includes("[medium] [testing]  src/app.ts:42"));
		assert.ok(lines.includes("Missing regression coverage"));
		assert.ok(lines.includes("Fix: Add a regression test."));
	});
});

describe("responseDisplayLines", () => {
	it("shows the author response body when present", () => {
		const lines = responseDisplayLines(finding({ response: "I disagree — this is intentional." }));
		assert.deepEqual(lines, ["Author response:", "I disagree — this is intentional."]);
	});

	it("shows a placeholder when the response is absent", () => {
		assert.deepEqual(responseDisplayLines(finding({})), ["Author response:", "—"]);
	});

	it("treats a whitespace-only response as absent", () => {
		assert.deepEqual(responseDisplayLines(finding({ response: "   " })), ["Author response:", "—"]);
	});
});
