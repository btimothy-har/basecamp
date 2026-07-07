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

function completedWaitResults(): Map<string, ReviewerWaitResult> {
	return new Map<string, ReviewerWaitResult>(
		REVIEWERS.map((spec) => [handleFor(spec), { status: "completed", result: `${spec.dimension} prose`, error: null }]),
	);
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
	it("dispatches every reviewer, transposes completed output, and returns merged ordered findings", async () => {
		const dispatched: { spec: ReviewerSpec; brief: string }[] = [];
		const waitedHandles: string[][] = [];
		const transposed: { output: string; dimension: Dimension }[] = [];
		const waitResults = completedWaitResults();
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
			transpose: async (output, dimension) => {
				transposed.push({ output, dimension });
				return findingsByDimension.get(dimension) ?? [];
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, true);
		if (!result.ok) assert.fail("expected review to succeed");
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
			result.result.findings.map((item) => item.title),
			["Token is logged", "Name hides intent"],
		);
		assert.deepEqual(result.result.verdict, {
			decision: "comment",
			blocking: false,
			counts: { critical: 0, high: 1, medium: 1, low: 0 },
		});
		assert.equal(result.result.createdAt, "2026-07-07T12:00:00.000Z");
	});

	it("fails the whole review when dispatch fails", async () => {
		let waitCalled = false;
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => {
				if (spec.dimension === "security") throw new Error("daemon unavailable");
				return handleFor(spec);
			},
			waitForReviewers: async () => {
				waitCalled = true;
				return completedWaitResults();
			},
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, "security-specialist");
		assert.equal(result.reason.startsWith("dispatch failed:"), true);
		assert.equal(waitCalled, false);
	});

	it("fails the whole review when waiting fails", async () => {
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => {
				throw new Error("daemon wait exploded");
			},
			transpose: async () => {
				throw new Error("transpose should not run");
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, "security-specialist");
		assert.equal(result.reason.startsWith("wait failed:"), true);
	});

	it("fails the whole review when a reviewer is not completed", async () => {
		const waitResults = completedWaitResults();
		const failedSpec = REVIEWERS[2]!;
		waitResults.set(handleFor(failedSpec), { status: "failed", result: "docs output", error: "review crashed" });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, failedSpec.agent);
		assert.equal(result.reason, "reviewer failed");
	});

	it("fails the whole review when a reviewer is still running", async () => {
		const waitResults = completedWaitResults();
		const runningSpec = REVIEWERS[3]!;
		waitResults.set(handleFor(runningSpec), { status: "running", result: "partial clarity output", error: null });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, runningSpec.agent);
		assert.equal(result.reason, "reviewer running (timed out)");
	});

	it("fails the whole review when a reviewer returns empty output", async () => {
		const waitResults = completedWaitResults();
		const emptySpec = REVIEWERS[4]!;
		waitResults.set(handleFor(emptySpec), { status: "completed", result: "   ", error: null });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, emptySpec.agent);
		assert.equal(result.reason, "reviewer returned no output");
	});

	it("fails the whole review when transpose throws", async () => {
		const throwingSpec = REVIEWERS[5]!;
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => completedWaitResults(),
			transpose: async (_output, dimension) => {
				if (dimension === throwingSpec.dimension) throw new Error("invalid tool payload");
				return [finding({ dimension, title: `${dimension} finding` })];
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, throwingSpec.agent);
		assert.equal(result.reason.startsWith("transpose failed:"), true);
	});

	it("reports the first failure by order", async () => {
		let waitCalled = false;
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => {
				if (spec.dimension === "security") throw new Error("daemon unavailable");
				return handleFor(spec);
			},
			waitForReviewers: async () => {
				waitCalled = true;
				return completedWaitResults();
			},
			transpose: async (_output, dimension) => {
				if (dimension === "docs") throw new Error("invalid tool payload");
				return [finding({ dimension, title: `${dimension} finding` })];
			},
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, "security-specialist");
		assert.equal(result.reason.startsWith("dispatch failed:"), true);
		assert.equal(waitCalled, false);
	});

	it("reports the first transpose-phase failure by reviewer order", async () => {
		const waitResults = completedWaitResults();
		waitResults.set(handleFor(REVIEWERS[0]!), { status: "failed", result: "security output", error: null });
		waitResults.set(handleFor(REVIEWERS[2]!), { status: "failed", result: "docs output", error: null });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, "security-specialist");
		assert.equal(result.reason, "reviewer failed");
	});

	it("fails the whole review when a reviewer wait status is unknown", async () => {
		const waitResults = completedWaitResults();
		const unknownSpec = REVIEWERS[1]!;
		waitResults.set(handleFor(unknownSpec), { status: "unknown", result: null, error: null });
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, unknownSpec.agent);
		assert.equal(result.reason, "reviewer unknown");
	});

	it("fails the whole review when a reviewer handle is missing from the wait results", async () => {
		const waitResults = completedWaitResults();
		waitResults.delete(handleFor(REVIEWERS[0]!));
		const deps: OrchestrateDeps = {
			dispatchReviewer: async (spec) => handleFor(spec),
			waitForReviewers: async () => waitResults,
			transpose: async (_output, dimension) => [finding({ dimension, title: `${dimension} finding` })],
			now: () => new Date("2026-07-07T12:00:00.000Z"),
		};

		const result = await runReview(scope, deps);

		assert.equal(result.ok, false);
		if (result.ok) assert.fail("expected review to fail");
		assert.equal(result.failedReviewer, "security-specialist");
		assert.equal(result.reason, "reviewer unknown");
	});
});
