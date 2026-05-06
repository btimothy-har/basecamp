import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ReviewPacket, ReviewReference } from "../review-packet.ts";
import {
	buildReviewDiffArgs,
	filterUnifiedDiffToNewLineRange,
	parseUnifiedDiff,
	REVIEW_DIFF_CONCURRENCY_LIMIT,
	REVIEW_DIFF_TIMEOUT_MS,
	resolveReviewPacketDiffs,
	truncateResolvedDiffText,
} from "../review-packet-diff.ts";

interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

interface ExecResult {
	code: number;
	stdout: string;
	stderr: string;
}

interface MockPi {
	execCalls: ExecCall[];
	exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }): Promise<ExecResult>;
}

function reference(overrides: Partial<ReviewReference> = {}): ReviewReference {
	return {
		path: "src/file.ts",
		whyRelevant: "supports the review",
		diff: { base: "main", head: "feature" },
		...overrides,
	};
}

function packet(references: ReviewReference[]): ReviewPacket {
	return {
		target: { kind: "branch", branch: "feature", base: "main" },
		cards: [{ id: "card", kind: "walkthrough", title: "Card", body: "Body", references }],
	};
}

function createMockPi(
	handler: (command: string, args: string[], options?: { cwd?: string; timeout?: number }) => Promise<ExecResult>,
): MockPi {
	return {
		execCalls: [],
		async exec(command, args, options) {
			this.execCalls.push({ command, args, options });
			return handler(command, args, options);
		},
	};
}

const SAMPLE_DIFF = `diff --git a/src/file.ts b/src/file.ts
index 1111111..2222222 100644
--- a/src/file.ts
+++ b/src/file.ts
@@ -1,3 +1,4 @@
 line 1
-old 2
+new 2
 line 3
+new 4
@@ -20,3 +21,4 @@
 line 21
-old 22
+new 22
 line 23
+new 24
`;

describe("buildReviewDiffArgs", () => {
	it("builds fixed git diff argv with explicit context, revision range, and diff path", () => {
		const args = buildReviewDiffArgs(
			reference({
				diff: { base: "origin/main", head: "abc123", path: "pi-extension/src/git/review-packet.ts", contextLines: 8 },
			}),
		);

		assert.deepEqual(args, [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=8",
			"origin/main...abc123",
			"--",
			"pi-extension/src/git/review-packet.ts",
		]);
	});

	it("uses default context and falls back to the reference path", () => {
		assert.deepEqual(buildReviewDiffArgs(reference({ path: "src/fallback.ts", diff: { base: "main" } })), [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"main",
			"--",
			"src/fallback.ts",
		]);
	});

	it("returns no argv for references without structured diff metadata", () => {
		assert.deepEqual(buildReviewDiffArgs(reference({ diff: undefined })), []);
	});

	it("rejects option, range, and whitespace revisions", () => {
		for (const base of ["-main", "main..feature", "main feature", " main", "main\nfeature", ""]) {
			assert.throws(
				() => buildReviewDiffArgs(reference({ diff: { base } })),
				/Review diff base must be a simple revision/,
			);
		}
		for (const head of ["-feature", "main..feature", "feature branch", "feature ", "feature\tbranch"]) {
			assert.throws(
				() => buildReviewDiffArgs(reference({ diff: { base: "main", head } })),
				/Review diff head must be a simple revision/,
			);
		}
	});
});

describe("unified diff helpers", () => {
	it("parses unified diff blocks and filters hunks by new-file line range", () => {
		const blocks = parseUnifiedDiff(SAMPLE_DIFF);
		assert.equal(blocks.length, 1);
		assert.equal(blocks[0]?.hunks.length, 2);

		const filtered = filterUnifiedDiffToNewLineRange(SAMPLE_DIFF, { start: 21, end: 24 });

		assert.ok(filtered);
		assert.match(filtered, /diff --git a\/src\/file\.ts b\/src\/file\.ts/);
		assert.doesNotMatch(filtered, /@@ -1,3 \+1,4 @@/);
		assert.match(filtered, /@@ -20,3 \+21,4 @@/);
		assert.match(filtered, /\+new 24/);
	});

	it("returns null when no hunk intersects the requested new-file line range", () => {
		assert.equal(filterUnifiedDiffToNewLineRange(SAMPLE_DIFF, { start: 200, end: 220 }), null);
	});

	it("sanitizes control characters and truncates resolved diff text", () => {
		assert.deepEqual(truncateResolvedDiffText("a\u001b[31mRED\u001b[0m\r\nb\u0007c"), {
			text: "aRED\nbc",
			truncated: false,
		});

		const truncated = truncateResolvedDiffText(`0123456789\r\n${"x".repeat(40)}`, 30);
		assert.equal(truncated.truncated, true);
		assert.ok(truncated.text.length <= 30);
		assert.match(truncated.text, /\[diff truncated\]/);
		assert.doesNotMatch(truncated.text, /\r/);
	});
});

describe("resolveReviewPacketDiffs", () => {
	it("does not execute git when no references include diff metadata", async () => {
		const mockPi = createMockPi(async () => {
			throw new Error("should not execute");
		});
		const input = packet([reference({ diff: undefined })]);

		const resolved = await resolveReviewPacketDiffs(mockPi as never, input);

		assert.equal(mockPi.execCalls.length, 0);
		assert.equal(resolved.cards[0]?.references?.[0]?.resolvedDiff, undefined);
	});

	it("resolves matching diff text and passes default timeout through the exec seam", async () => {
		const mockPi = createMockPi(async () => ({ code: 0, stdout: SAMPLE_DIFF, stderr: "" }));

		const resolved = await resolveReviewPacketDiffs(mockPi as never, packet([reference()]), { cwd: "/tmp/worktree" });
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(resolvedDiff?.status, "resolved");
		assert.equal(resolvedDiff?.truncated, false);
		assert.match(resolvedDiff?.text ?? "", /\+new 24/);
		assert.deepEqual(mockPi.execCalls[0], {
			command: "git",
			args: ["diff", "--no-ext-diff", "--no-color", "--unified=3", "main...feature", "--", "src/file.ts"],
			options: { cwd: "/tmp/worktree", timeout: REVIEW_DIFF_TIMEOUT_MS },
		});
	});

	it("returns no_match for empty git diff output and for non-intersecting line ranges", async () => {
		const mockPi = createMockPi(async (_command, args) => {
			const path = args.at(-1);
			return { code: 0, stdout: path === "src/empty.ts" ? "" : SAMPLE_DIFF, stderr: "" };
		});

		const resolved = await resolveReviewPacketDiffs(
			mockPi as never,
			packet([
				reference({ path: "src/empty.ts", diff: { base: "main" } }),
				reference({ path: "src/ranged.ts", diff: { base: "main", lineStart: 200, lineEnd: 210 } }),
			]),
		);

		assert.equal(resolved.cards[0]?.references?.[0]?.resolvedDiff?.status, "no_match");
		assert.match(resolved.cards[0]?.references?.[0]?.resolvedDiff?.message ?? "", /no output/i);
		assert.equal(resolved.cards[0]?.references?.[1]?.resolvedDiff?.status, "no_match");
		assert.match(resolved.cards[0]?.references?.[1]?.resolvedDiff?.message ?? "", /line range 200-210/);
	});

	it("returns git_error for non-zero git exits and thrown exec errors without throwing", async () => {
		const mockPi = createMockPi(async (_command, args) => {
			const path = args.at(-1);
			if (path === "src/throws.ts") throw new Error("boom\u001b[31m red\u001b[0m\r\nnext");
			return { code: 128, stdout: "", stderr: "fatal:\u001b[31m bad ref\u001b[0m\r\n" };
		});

		const resolved = await resolveReviewPacketDiffs(
			mockPi as never,
			packet([
				reference({ path: "src/git-error.ts", diff: { base: "main" } }),
				reference({ path: "src/throws.ts", diff: { base: "main" } }),
			]),
		);

		const gitError = resolved.cards[0]?.references?.[0]?.resolvedDiff;
		assert.equal(gitError?.status, "git_error");
		assert.equal(gitError?.message, "fatal: bad ref");
		assert.equal(gitError?.truncated, false);
		assert.deepEqual(gitError?.args, [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"main",
			"--",
			"src/git-error.ts",
		]);

		const thrownError = resolved.cards[0]?.references?.[1]?.resolvedDiff;
		assert.equal(thrownError?.status, "git_error");
		assert.equal(thrownError?.message, "boom red\nnext");
		assert.equal(thrownError?.truncated, false);
		assert.deepEqual(thrownError?.args, [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"main",
			"--",
			"src/throws.ts",
		]);
	});

	it("caps concurrent git diff executions", async () => {
		let active = 0;
		let maxActive = 0;
		const mockPi = createMockPi(async () => {
			active += 1;
			maxActive = Math.max(maxActive, active);
			await new Promise((resolve) => setTimeout(resolve, 1));
			active -= 1;
			return { code: 0, stdout: SAMPLE_DIFF, stderr: "" };
		});
		const references = Array.from({ length: REVIEW_DIFF_CONCURRENCY_LIMIT * 3 }, (_, index) =>
			reference({ path: `src/file-${index}.ts`, diff: { base: "main" } }),
		);

		await resolveReviewPacketDiffs(mockPi as never, packet(references));

		assert.equal(mockPi.execCalls.length, REVIEW_DIFF_CONCURRENCY_LIMIT * 3);
		assert.ok(maxActive <= REVIEW_DIFF_CONCURRENCY_LIMIT, `expected ${maxActive} <= ${REVIEW_DIFF_CONCURRENCY_LIMIT}`);
	});
});
