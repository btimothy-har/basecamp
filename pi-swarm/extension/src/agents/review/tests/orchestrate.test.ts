import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Dimension, Finding } from "../findings.ts";
import {
	buildReviewerBrief,
	type OrchestrateDeps,
	REVIEWERS,
	type ReviewerSpec,
	type ReviewerWaitResult,
	type ReviewScope,
	runReview,
} from "../orchestrate.ts";

const scope: ReviewScope = {
	base: "main",
	head: "feature",
	cwd: "/repo",
	label: "feature review",
};

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

function handleFor(spec: ReviewerSpec): string {
	return `handle:${spec.agent}`;
}

describe("buildReviewerBrief", () => {
	it("builds a fixed scope-only brief", () => {
		assert.equal(
			buildReviewerBrief(scope),
			"Review the code changes in the diff between main and feature in the working directory /repo. Run git yourself to inspect the changes (e.g. git diff main...feature, git diff --stat, and read the changed files directly). Assess only what your specialist role covers. Report findings only — do not modify files or write fixes.",
		);
	});
});

describe("runReview", () => {
	it("dispatches every reviewer, transposes completed prose, and returns merged ordered findings", async () => {
		const dispatched: { spec: ReviewerSpec; brief: string }[] = [];
		const waitedHandles: string[][] = [];
		const transposed: { prose: string; dimension: Dimension }[] = [];
		const waitResults = new Map<string, ReviewerWaitResult>(
			REVIEWERS.map((spec) => [
				handleFor(spec),
				{ status: "completed", result: `${spec.dimension} prose`, error: null },
			]),
		);
		const findingsByDimension = new Map<Dimension, Finding[]>([
			[
				"security",
				[
					finding({
						dimension: "security",
						severity: "high",
						file: "src/auth.ts",
						lineStart: 20,
						lineEnd: 22,
						title: "Token is logged",
					}),
				],
			],
			["testing", []],
			["docs", []],
			[
				"clarity",
				[
					finding({
						dimension: "clarity",
						severity: "medium",
						file: "src/app.ts",
						lineStart: 4,
						lineEnd: 4,
						title: "Name hides intent",
					}),
				],
			],
			["conventions", []],
			["general", []],
		]);
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec, brief) => {
				dispatched.push({ spec, brief });
				return handleFor(spec);
			},
			waitForReviewers: async (handles) => {
				waitedHandles.push(handles);
				return waitResults;
			},
			transpose: async (prose, dimension) => {
				transposed.push({ prose, dimension });
				return findingsByDimension.get(dimension) ?? [];
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.deepEqual(
			dispatched.map((item) => item.spec.agent),
			REVIEWERS.map((spec) => spec.agent),
		);
		assert.equal(new Set(dispatched.map((item) => item.brief)).size, 1);
		assert.deepEqual(waitedHandles, [REVIEWERS.map(handleFor)]);
		assert.deepEqual(
			transposed.map((item) => item.dimension),
			REVIEWERS.map((spec) => spec.dimension),
		);
		assert.deepEqual(
			result.findings.map((item) => item.title),
			["Token is logged", "Name hides intent"],
		);
		assert.deepEqual(result.verdict, {
			decision: "comment",
			blocking: false,
			counts: { critical: 0, high: 1, medium: 1, low: 0 },
		});
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.agent),
			REVIEWERS.map((spec) => spec.agent),
		);
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.gap),
			[null, null, null, null, null, null],
		);
		assert.equal(result.createdAt, "2026-07-07T12:00:00.000Z");
	});

	it("degrades gracefully for dispatch, wait-result, transpose, and empty-output failures", async () => {
		const waitResults = new Map<string, ReviewerWaitResult>([
			["handle:testing-specialist", { status: "failed", result: "testing prose", error: "review crashed" }],
			["handle:docs-specialist", { status: "completed", result: "docs prose", error: null }],
			["handle:code-clarity-specialist", { status: "completed", result: "   ", error: null }],
			["handle:conventions-specialist", { status: "completed", result: "conventions prose", error: null }],
			["handle:general-reviewer", { status: "completed", result: "general prose", error: null }],
		]);
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => {
				if (spec.dimension === "security") throw new Error("daemon unavailable");
				return handleFor(spec);
			},
			waitForReviewers: async () => waitResults,
			transpose: async (_prose, dimension) => {
				if (dimension === "docs") throw new Error("invalid tool payload");
				if (dimension === "general") {
					return [
						finding({
							dimension: "general",
							severity: "critical",
							file: "src/payments.ts",
							lineStart: 99,
							lineEnd: 99,
							title: "Payments can be double charged",
						}),
					];
				}
				return [];
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.deepEqual(result.verdict, {
			decision: "request-changes",
			blocking: true,
			counts: { critical: 1, high: 0, medium: 0, low: 0 },
		});
		assert.deepEqual(
			result.findings.map((item) => item.title),
			["Payments can be double charged"],
		);
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.agent),
			REVIEWERS.map((spec) => spec.agent),
		);
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.gap),
			[
				"dispatch failed: daemon unavailable",
				"reviewer failed",
				"transpose failed: invalid tool payload",
				"reviewer returned no output",
				null,
				null,
			],
		);

		const testingOutcome = result.reviewers.find((reviewer) => reviewer.agent === "testing-specialist");
		assert.equal(testingOutcome?.prose, "testing prose");
		assert.equal(testingOutcome?.error, "review crashed");

		const docsOutcome = result.reviewers.find((reviewer) => reviewer.agent === "docs-specialist");
		assert.equal(docsOutcome?.prose, "docs prose");
		assert.equal(docsOutcome?.error, "invalid tool payload");
	});

	it("marks dispatched reviewers unknown when waitForReviewers throws", async () => {
		const dispatched: ReviewerSpec[] = [];
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => {
				dispatched.push(spec);
				return handleFor(spec);
			},
			waitForReviewers: async () => {
				throw new Error("daemon wait exploded");
			},
			transpose: async () => {
				throw new Error("transpose should not run");
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.deepEqual(
			dispatched.map((spec) => spec.agent),
			REVIEWERS.map((spec) => spec.agent),
		);
		assert.deepEqual(result.verdict, {
			decision: "approve",
			blocking: false,
			counts: { critical: 0, high: 0, medium: 0, low: 0 },
		});
		assert.deepEqual(result.findings, []);
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.status),
			["unknown", "unknown", "unknown", "unknown", "unknown", "unknown"],
		);
		assert.equal(
			result.reviewers.every((reviewer) => reviewer.gap?.startsWith("wait failed:")),
			true,
		);
	});

	it("records running wait results as timed-out coverage gaps with no findings", async () => {
		const waitResults = new Map<string, ReviewerWaitResult>(
			REVIEWERS.map((spec) => [
				handleFor(spec),
				{ status: "completed", result: `${spec.dimension} prose`, error: null },
			]),
		);
		waitResults.set(handleFor(REVIEWERS[0]!), { status: "running", result: "partial security prose", error: null });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_prose, dimension) => [finding({ dimension, severity: "low", title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);
		const runningOutcome = result.reviewers.find((reviewer) => reviewer.agent === REVIEWERS[0]?.agent);

		assert.equal(runningOutcome?.status, "running");
		assert.equal(runningOutcome?.gap, "reviewer running (timed out)");
		assert.deepEqual(runningOutcome?.findings, []);
		assert.equal(runningOutcome?.prose, "partial security prose");
		assert.deepEqual(
			result.findings.map((item) => item.title),
			["testing finding", "docs finding", "clarity finding", "conventions finding", "general finding"],
		);
	});

	it("does not wait when every dispatch fails and approves with no findings", async () => {
		let waitCalled = false;
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => {
				throw new Error(`dispatch unavailable for ${spec.agent}`);
			},
			waitForReviewers: async () => {
				waitCalled = true;
				throw new Error("wait should not run");
			},
			transpose: async () => {
				throw new Error("transpose should not run");
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(waitCalled, false);
		assert.deepEqual(result.verdict, {
			decision: "approve",
			blocking: false,
			counts: { critical: 0, high: 0, medium: 0, low: 0 },
		});
		assert.deepEqual(result.findings, []);
		assert.deepEqual(
			result.reviewers.map((reviewer) => reviewer.status),
			["failed", "failed", "failed", "failed", "failed", "failed"],
		);
		assert.equal(
			result.reviewers.every((reviewer) => reviewer.gap?.startsWith("dispatch failed:")),
			true,
		);
	});
});
