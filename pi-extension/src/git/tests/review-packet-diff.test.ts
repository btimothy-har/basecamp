import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { ReviewPacket, ReviewReference } from "../review-packet.ts";
import {
	buildReviewDiffArgs,
	filterUnifiedDiffToNewLineRange,
	resolveReviewPacketDiffs,
	truncateResolvedDiffText,
} from "../review-packet-diff.ts";

interface ExecCall {
	command: string;
	args: string[];
	options?: { cwd?: string; timeout?: number };
}

function packetWithReference(reference: ReviewReference): ReviewPacket {
	return {
		target: { kind: "branch", branch: "feature", base: "main" },
		cards: [
			{
				id: "diff-card",
				kind: "diff-evidence",
				title: "Diff evidence",
				body: "Review the diff.",
				references: [reference],
			},
		],
	};
}

function mockPi(result: { code: number; stdout?: string; stderr?: string }): { pi: ExtensionAPI; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }) {
			calls.push({ command, args, options });
			return { code: result.code, stdout: result.stdout ?? "", stderr: result.stderr ?? "" };
		},
	} as unknown as ExtensionAPI;
	return { pi, calls };
}

function throwingPi(error: Error): { pi: ExtensionAPI; calls: ExecCall[] } {
	const calls: ExecCall[] = [];
	const pi = {
		async exec(command: string, args: string[], options?: { cwd?: string; timeout?: number }) {
			calls.push({ command, args, options });
			throw error;
		},
	} as unknown as ExtensionAPI;
	return { pi, calls };
}

const TWO_HUNK_DIFF = `diff --git a/src/file.ts b/src/file.ts
index 1111111..2222222 100644
--- a/src/file.ts
+++ b/src/file.ts
@@ -1,3 +1,3 @@
 unchanged
-old one
+new one
 tail
@@ -20,3 +20,4 @@
 context
-old two
+new two
+new three
 tail
`;

describe("review packet diff helpers", () => {
	it("builds controlled read-only git diff argv from structured fields", () => {
		const reference: ReviewReference = {
			path: "src/fallback.ts",
			whyRelevant: "shows the diff",
			diff: {
				base: "main",
				head: "feature/review",
				path: "src/file.ts",
				contextLines: 5,
			},
		};

		assert.deepEqual(buildReviewDiffArgs(reference), [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=5",
			"main...feature/review",
			"--",
			"src/file.ts",
		]);
	});

	it("uses small default context and falls back to the review reference path", () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "shows the diff",
			diff: { base: "main" },
		};

		assert.deepEqual(buildReviewDiffArgs(reference), [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"main",
			"--",
			"src/file.ts",
		]);
	});

	it("rejects range-like or option-like structured revisions", () => {
		for (const diff of [{ base: "main..feature" }, { base: "main", head: "--cached" }]) {
			assert.throws(
				() => buildReviewDiffArgs({ path: "src/file.ts", whyRelevant: "shows the diff", diff }),
				/simple revision, not an option or range/,
			);
		}
	});

	it("keeps only unified diff hunks whose new-file range intersects the requested range", () => {
		const filtered = filterUnifiedDiffToNewLineRange(TWO_HUNK_DIFF, { start: 21, end: 21 });

		assert.ok(filtered?.includes("diff --git a/src/file.ts b/src/file.ts"));
		assert.ok(filtered?.includes("@@ -20,3 +20,4 @@"));
		assert.ok(filtered?.includes("+new two"));
		assert.equal(filtered?.includes("@@ -1,3 +1,3 @@"), false);
		assert.equal(filtered?.includes("+new one"), false);
	});

	it("sanitizes and truncates resolved diff text", () => {
		const result = truncateResolvedDiffText("abc\u001b[31mdef\u007fg\r\nhijklmnopqrstuvwxyz", 20);

		assert.equal(result.truncated, true);
		assert.equal(result.text, "ab\n[diff truncated]\n");
		assert.equal(truncateResolvedDiffText("abcdefghijklmnopqrstuvwxyz", 4).text.length, 4);
	});

	it("returns references without diff unchanged and does not execute git", async () => {
		const reference: ReviewReference = { path: "src/file.ts", whyRelevant: "quote-only reference" };
		const { pi, calls } = mockPi({ code: 0, stdout: "unexpected" });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));

		assert.equal(calls.length, 0);
		assert.deepEqual(resolved.cards[0]?.references?.[0], reference);
	});

	it("records resolved range-filtered diffs for intersecting hunks", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "line-specific diff",
			diff: { base: "main", head: "feature", lineStart: 21, lineEnd: 21 },
		};
		const { pi } = mockPi({ code: 0, stdout: TWO_HUNK_DIFF });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(resolvedDiff?.status, "resolved");
		assert.ok(resolvedDiff?.text?.includes("@@ -20,3 +20,4 @@"));
		assert.ok(resolvedDiff?.text?.includes("+new two"));
		assert.equal(resolvedDiff?.text?.includes("+new one"), false);
		assert.deepEqual(resolvedDiff?.args, [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"main...feature",
			"--",
			"src/file.ts",
		]);
	});

	it("records no_match for line ranges with no intersecting hunk", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "line-specific diff",
			diff: { base: "main", head: "feature", lineStart: 100, lineEnd: 101 },
		};
		const { pi } = mockPi({ code: 0, stdout: TWO_HUNK_DIFF });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(resolvedDiff?.status, "no_match");
		assert.match(resolvedDiff?.message ?? "", /No diff hunk intersects/);
	});

	it("records no_match for empty full diff output", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "empty diff",
			diff: { base: "main" },
		};
		const { pi } = mockPi({ code: 0, stdout: "" });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(resolvedDiff?.status, "no_match");
		assert.match(resolvedDiff?.message ?? "", /git diff produced no output/);
	});

	it("surfaces truncation through resolved diff evidence", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "large diff",
			diff: { base: "main" },
		};
		const { pi } = mockPi({ code: 0, stdout: "abcdefghijklmnopqrstuvwxyz" });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference), { maxChars: 20 });
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(resolvedDiff?.status, "resolved");
		assert.equal(resolvedDiff?.truncated, true);
		assert.equal(resolvedDiff?.text, "ab\n[diff truncated]\n");
	});

	it("records git failures per reference without aborting the packet", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "failing diff",
			diff: { base: "missing-ref", head: "feature" },
		};
		const { pi, calls } = mockPi({ code: 128, stderr: "fatal: \u001b[31mbad revision\u001b[0m" });

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(calls.length, 1);
		assert.equal(calls[0]?.command, "git");
		assert.deepEqual(resolvedDiff?.args, [
			"diff",
			"--no-ext-diff",
			"--no-color",
			"--unified=3",
			"missing-ref...feature",
			"--",
			"src/file.ts",
		]);
		assert.equal(resolvedDiff?.status, "git_error");
		assert.equal(resolvedDiff?.message, "fatal: bad revision");
	});

	it("records thrown git execution errors per reference", async () => {
		const reference: ReviewReference = {
			path: "src/file.ts",
			whyRelevant: "throwing diff",
			diff: { base: "main" },
		};
		const { pi, calls } = throwingPi(new Error("spawn failed"));

		const resolved = await resolveReviewPacketDiffs(pi, packetWithReference(reference));
		const resolvedDiff = resolved.cards[0]?.references?.[0]?.resolvedDiff;

		assert.equal(calls.length, 1);
		assert.equal(resolvedDiff?.status, "git_error");
		assert.equal(resolvedDiff?.message, "spawn failed");
	});
});
