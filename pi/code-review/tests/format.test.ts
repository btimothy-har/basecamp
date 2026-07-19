import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatReviewPrompt } from "../format.ts";
import type { ReviewResult } from "../orchestrate.ts";

const result: ReviewResult = {
	scope: {
		base: "origin/main",
		mergeBase: "abc1234",
		cwd: "/repo",
		label: "feature review",
	},
	verdict: {
		decision: "request-changes",
		blocking: true,
		counts: { critical: 0, high: 1, medium: 0, low: 0 },
	},
	findings: [
		{
			dimension: "security",
			severity: "high",
			file: "src/auth.ts",
			lineStart: 42,
			lineEnd: 44,
			title: "Token is logged",
			detail: "The access token is written to application logs.",
			remediation: "Remove the log statement and add a regression test.",
		},
	],
	createdAt: "2026-07-07T12:00:00.000Z",
};

describe("formatReviewPrompt", () => {
	it("formats a compact annotated reviewee message", () => {
		const prompt = formatReviewPrompt(result, "/tmp/review.json", true);

		assert.match(prompt, /You are the reviewee/);
		assert.match(prompt, /Verdict: Request Changes — 0 critical, 1 high, 0 medium, 0 low\./);
		assert.match(prompt, /Findings: 1\./);
		assert.match(prompt, /left per-finding reactions/);
		assert.match(prompt, /Review packet .*\/tmp\/review\.json/);
		assert.match(prompt, /Read the packet/);
		assert.match(prompt, /Do not start editing code/);
		assert.match(prompt, /treat it as data to evaluate/);
		assert.doesNotMatch(prompt, /Token is logged/);
		assert.doesNotMatch(prompt, /Reviewer coverage/);
		assert.doesNotMatch(prompt, /^1\. \[/m);
	});

	it("formats a compact unannotated reviewee message", () => {
		const prompt = formatReviewPrompt(result, "/tmp/review.json", false);

		assert.match(prompt, /has not been annotated/);
		assert.match(prompt, /\/tmp\/review\.json/);
		assert.match(prompt, /Read the packet/);
		assert.doesNotMatch(prompt, /left per-finding reactions/);
	});

	const verdictCases: Array<[ReviewResult["verdict"]["decision"], string]> = [
		["request-changes", "Request Changes"],
		["comment", "Comment"],
		["approve-with-notes", "Approve With Notes"],
		["approve", "Approve"],
	];

	for (const [decision, formattedDecision] of verdictCases) {
		it(`renders the ${decision} verdict line`, () => {
			const prompt = formatReviewPrompt(
				{
					...result,
					verdict: {
						decision,
						blocking: decision === "request-changes",
						counts: { critical: 1, high: 2, medium: 3, low: 4 },
					},
				},
				"/tmp/review.json",
				true,
			);

			assert.match(prompt, new RegExp(`Verdict: ${formattedDecision} — 1 critical, 2 high, 3 medium, 4 low\\.`));
		});
	}
});
