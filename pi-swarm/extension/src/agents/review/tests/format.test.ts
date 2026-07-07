import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatReviewPrompt } from "../format.ts";
import type { ReviewResult } from "../orchestrate.ts";

const result: ReviewResult = {
	scope: {
		base: "main",
		head: "feature",
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
	reviewers: [
		{
			agent: "security-specialist",
			dimension: "security",
			status: "completed",
			prose: "security prose",
			error: null,
			findings: [],
			gap: null,
		},
		{
			agent: "testing-specialist",
			dimension: "testing",
			status: "failed",
			prose: "testing prose",
			error: "review crashed",
			findings: [],
			gap: "reviewer failed",
		},
		{
			agent: "docs-specialist",
			dimension: "docs",
			status: "completed",
			prose: "docs prose",
			error: null,
			findings: [],
			gap: null,
		},
		{
			agent: "code-clarity-specialist",
			dimension: "clarity",
			status: "completed",
			prose: "clarity prose",
			error: null,
			findings: [],
			gap: null,
		},
		{
			agent: "conventions-specialist",
			dimension: "conventions",
			status: "completed",
			prose: "conventions prose",
			error: null,
			findings: [],
			gap: null,
		},
		{
			agent: "general-reviewer",
			dimension: "general",
			status: "completed",
			prose: "general prose",
			error: null,
			findings: [],
			gap: null,
		},
	],
	createdAt: "2026-07-07T12:00:00.000Z",
};

describe("formatReviewPrompt", () => {
	it("formats verdict, structured findings, coverage, artifact path, and reviewee next-step framing", () => {
		const prompt = formatReviewPrompt(result, "/tmp/review.json");

		assert.match(prompt, /You are the reviewee/);
		assert.match(prompt, /Verdict: Request Changes — 0 critical, 1 high, 0 medium, 0 low\./);
		assert.match(prompt, /1\. \[high\] \[security\] src\/auth\.ts:42 — Token is logged/);
		assert.match(prompt, /The access token is written to application logs\./);
		assert.match(prompt, /Fix: Remove the log statement and add a regression test\./);
		assert.match(prompt, /- security-specialist: ok/);
		assert.match(prompt, /- testing-specialist: reviewer failed/);
		assert.match(prompt, /- conventions-specialist: ok/);
		assert.match(prompt, /Full report \+ raw reviewer output: \/tmp\/review\.json/);
		assert.match(prompt, /confirm it with the user before editing code/);
	});
});
