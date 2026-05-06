import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DisplayReviewCard } from "../review-packet-diff.ts";
import { REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH, renderReviewCardContent } from "../review-packet-review.ts";

function card(overrides: Partial<DisplayReviewCard> = {}): DisplayReviewCard {
	return {
		id: "card",
		kind: "walkthrough",
		title: "Review card",
		body: "These are the review notes.",
		...overrides,
	};
}

describe("renderReviewCardContent", () => {
	it("renders resolved diff evidence in columns at wide widths", () => {
		const lines = renderReviewCardContent(
			card({
				references: [
					{
						path: "src/file.ts",
						lineStart: 10,
						lineEnd: 12,
						whyRelevant: "shows the changed branch",
						resolvedDiff: {
							status: "resolved",
							text: "@@ -10,2 +10,2 @@\n-old\n+new",
							truncated: false,
							args: ["diff"],
						},
					},
				],
			}),
			{ width: REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH + 24, feedbackCategoryLabel: "Approved" },
		);
		const output = lines.join("\n");

		assert.ok(lines.some((line) => line.includes(" │ ")));
		assert.match(output, /State: Approved/);
		assert.match(output, /Resolved diff status: resolved/);
		assert.match(output, /\+new/);
	});

	it("falls back to stacked sections for resolved diff evidence at narrow widths", () => {
		const lines = renderReviewCardContent(
			card({
				references: [
					{
						path: "src/file.ts",
						whyRelevant: "shows the changed branch",
						resolvedDiff: {
							status: "resolved",
							text: "+narrow",
							truncated: false,
							args: ["diff"],
						},
					},
				],
			}),
			{ width: REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH - 1, feedbackCategoryLabel: "Pending" },
		);
		const output = lines.join("\n");

		assert.equal(lines.includes("Evidence"), true);
		assert.equal(
			lines.some((line) => line.includes(" │ ")),
			false,
		);
		assert.match(output, /Resolved diff status: resolved/);
		assert.match(output, /\+narrow/);
	});

	it("keeps quote-only references stacked and includes the quote", () => {
		const lines = renderReviewCardContent(
			card({
				references: [
					{
						path: "src/file.ts",
						whyRelevant: "anchors the walkthrough",
						quote: "const value = 1;",
					},
				],
			}),
			{ width: REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH + 24, feedbackCategoryLabel: "Pending" },
		);
		const output = lines.join("\n");

		assert.equal(lines.includes("Evidence"), true);
		assert.equal(
			lines.some((line) => line.includes(" │ ")),
			false,
		);
		assert.match(output, /Quote:/);
		assert.match(output, /const value = 1;/);
	});

	it("omits an evidence section for prose-only cards", () => {
		const lines = renderReviewCardContent(card(), {
			width: REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH + 24,
			feedbackCategoryLabel: "Pending",
		});

		assert.equal(lines.includes("Evidence"), false);
		assert.match(lines.join("\n"), /Review notes\nThese are the review notes\./);
	});

	it("renders failed and truncated resolved diff statuses and messages", () => {
		const lines = renderReviewCardContent(
			card({
				references: [
					{
						path: "src/missing.ts",
						whyRelevant: "shows missing evidence",
						resolvedDiff: {
							status: "no_match",
							message: "No diff hunk intersects requested new-file line range 20-30.",
							truncated: false,
							args: ["diff"],
						},
					},
					{
						path: "src/error.ts",
						whyRelevant: "shows git failure",
						resolvedDiff: {
							status: "git_error",
							message: "fatal: bad revision",
							truncated: true,
							args: ["diff"],
						},
					},
				],
			}),
			{ width: REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH - 1, feedbackCategoryLabel: "Pending" },
		);
		const output = lines.join("\n");

		assert.match(output, /Resolved diff status: no_match/);
		assert.match(output, /line range 20-30/);
		assert.match(output, /Resolved diff status: git_error \(truncated\)/);
		assert.match(output, /fatal: bad revision/);
	});
});
