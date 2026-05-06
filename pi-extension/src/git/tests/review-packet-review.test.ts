import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { DisplayReviewCard } from "../review-packet-diff.ts";
import { renderReviewCardContent } from "../review-packet-review.ts";

function diffCard(): DisplayReviewCard {
	return {
		id: "diff-card",
		kind: "diff-evidence",
		title: "Diff evidence",
		body: "Review the implementation approach, not the raw patch.",
		references: [
			{
				path: "src/file.ts",
				lineStart: 10,
				lineEnd: 12,
				commit: "abc123",
				quote: "+existing quote",
				whyRelevant: "Shows the concrete changed lines.",
				resolvedDiff: {
					status: "resolved",
					text: "diff --git a/src/file.ts b/src/file.ts\n-old\n+new\n",
					truncated: false,
					args: ["diff", "main", "--", "src/file.ts"],
				},
			},
		],
	};
}

describe("renderReviewCardContent", () => {
	it("splits prose and resolved diff evidence into columns when there is enough width", () => {
		const lines = renderReviewCardContent(diffCard(), { stateLabel: "Pending", width: 120 });
		const text = lines.join("\n");

		assert.ok(lines.some((line) => line.includes(" │ ")));
		assert.ok(text.includes("Prose"));
		assert.ok(text.includes("Evidence"));
		assert.ok(text.includes("Resolved diff status: resolved"));
		assert.ok(text.includes("+new"));
		assert.ok(lines.every((line) => line.length <= 120));
		const bodyLine = lines.find((line) => line.includes("Review the implementation approach")) ?? "";
		assert.equal(bodyLine.includes("+new"), false);
	});

	it("falls back to stacked sections at narrow widths", () => {
		const lines = renderReviewCardContent(diffCard(), { stateLabel: "Pending", width: 60 });

		assert.ok(lines.includes("Prose"));
		assert.ok(lines.includes("Evidence"));
		assert.equal(
			lines.some((line) => line.includes(" │ ")),
			false,
		);
		assert.ok(lines.every((line) => line.length <= 60));
	});

	it("preserves readable prose and quote evidence for cards without resolved diffs", () => {
		const card: DisplayReviewCard = {
			id: "quote-card",
			kind: "walkthrough",
			title: "Quote evidence",
			body: "Body remains readable.",
			references: [{ path: "src/file.ts", whyRelevant: "Supports the note.", quote: "quoted excerpt" }],
		};

		const lines = renderReviewCardContent(card, { stateLabel: "Approved", width: 80 });
		const text = lines.join("\n");

		assert.equal(
			lines.some((line) => line.includes(" │ ")),
			false,
		);
		assert.ok(text.includes("Review notes\nBody remains readable."));
		assert.ok(text.includes("Code / diff evidence"));
		assert.ok(text.includes("quoted excerpt"));
		assert.ok(lines.every((line) => line.length <= 80));
	});

	it("renders prose-only cards without an evidence section", () => {
		const card: DisplayReviewCard = {
			id: "prose-card",
			kind: "orientation",
			title: "Orientation",
			body: "Only prose is needed.",
		};

		const lines = renderReviewCardContent(card, { stateLabel: "Pending", width: 80 });
		const text = lines.join("\n");

		assert.ok(text.includes("Review notes\nOnly prose is needed."));
		assert.equal(text.includes("Code / diff evidence"), false);
		assert.equal(
			lines.some((line) => line.includes(" │ ")),
			false,
		);
	});

	it("renders truncated and failed resolved diff statuses", () => {
		const card: DisplayReviewCard = {
			id: "status-card",
			kind: "risk",
			title: "Diff status",
			body: "Inspect evidence status.",
			references: [
				{
					path: "src/large.ts",
					whyRelevant: "Large diff evidence.",
					resolvedDiff: { status: "resolved", text: "+large", truncated: true, args: ["diff"] },
				},
				{
					path: "src/missing.ts",
					whyRelevant: "Missing diff evidence.",
					resolvedDiff: { status: "git_error", message: "fatal: bad revision", truncated: false, args: ["diff"] },
				},
			],
		};

		const text = renderReviewCardContent(card, { stateLabel: "Pending", width: 120 }).join("\n");

		assert.ok(text.includes("Resolved diff status: resolved (truncated)"));
		assert.ok(text.includes("Resolved diff status: git_error"));
		assert.ok(text.includes("Resolved diff message: fatal: bad revision"));
	});
});
