import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	consolidateReviewFeedback,
	normalizeReviewCards,
	normalizeReviewPacket,
	type ReviewCard,
	type ReviewFeedback,
	type ReviewPacket,
	reviewFeedbackCategoryLabel,
	reviewFeedbackRequiresText,
} from "../review-packet.ts";

function card(overrides: Partial<ReviewCard>): ReviewCard {
	return {
		id: "card",
		kind: "walkthrough",
		title: "Title",
		body: "Body",
		...overrides,
	};
}

describe("normalizeReviewCards", () => {
	it("orders cards by review packet walkthrough order while preserving same-kind order", () => {
		const cards = normalizeReviewCards([
			card({ id: "risk-1", kind: "risk", title: "Risk" }),
			card({ id: "walkthrough-1", kind: "walkthrough", title: "Walkthrough 1" }),
			card({ id: "orientation-1", kind: "orientation", title: "Orientation" }),
			card({ id: "walkthrough-2", kind: "walkthrough", title: "Walkthrough 2" }),
			card({ id: "decision-1", kind: "decision", title: "Decision" }),
		]);

		assert.deepEqual(
			cards.map((item) => item.id),
			["orientation-1", "walkthrough-1", "walkthrough-2", "decision-1", "risk-1"],
		);
	});

	it("trims card fields and references without mutating the input", () => {
		const input = [
			card({
				id: " orientation ",
				kind: "orientation",
				title: " Orientation ",
				body: " Body ",
				references: [
					{
						path: " src/file.ts ",
						lineStart: 10,
						lineEnd: 12,
						commit: " abc123 ",
						quote: " quote ",
						whyRelevant: " explains the change ",
					},
				],
			}),
		];

		const cards = normalizeReviewCards(input);

		assert.equal(cards[0]?.id, "orientation");
		assert.equal(cards[0]?.title, "Orientation");
		assert.equal(cards[0]?.body, "Body");
		assert.deepEqual(cards[0]?.references?.[0], {
			path: "src/file.ts",
			lineStart: 10,
			lineEnd: 12,
			commit: "abc123",
			quote: "quote",
			whyRelevant: "explains the change",
		});
		assert.equal(input[0]?.id, " orientation ");
	});

	it("accepts and trims structured diff references", () => {
		const cards = normalizeReviewCards([
			card({
				id: "diff-card",
				references: [
					{
						path: " src/review-packet.ts ",
						whyRelevant: " shows the normalized shape ",
						diff: {
							base: " main ",
							head: " feature/review-packet ",
							path: " pi-extension/src/git/review-packet.ts ",
							lineStart: 20,
							lineEnd: 30,
							contextLines: 4,
						},
					},
				],
			}),
		]);

		assert.deepEqual(cards[0]?.references?.[0], {
			path: "src/review-packet.ts",
			lineStart: undefined,
			lineEnd: undefined,
			commit: undefined,
			quote: undefined,
			diff: {
				base: "main",
				head: "feature/review-packet",
				path: "pi-extension/src/git/review-packet.ts",
				lineStart: 20,
				lineEnd: 30,
				contextLines: 4,
			},
			whyRelevant: "shows the normalized shape",
		});
	});

	it("keeps quote-only references working without a diff reference", () => {
		const cards = normalizeReviewCards([
			card({
				references: [{ path: "src/file.ts", quote: " old evidence ", whyRelevant: " supports the claim " }],
			}),
		]);

		assert.deepEqual(cards[0]?.references?.[0], {
			path: "src/file.ts",
			lineStart: undefined,
			lineEnd: undefined,
			commit: undefined,
			quote: "old evidence",
			whyRelevant: "supports the claim",
		});
	});

	it("rejects duplicate or empty stable ids", () => {
		assert.throws(
			() => normalizeReviewCards([card({ id: "same" }), card({ id: " same ", title: "Other" })]),
			/Duplicate review card id: same/,
		);
		assert.throws(() => normalizeReviewCards([card({ id: " " })]), /Review card id is required/);
	});

	it("rejects invalid structured diff references", () => {
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [
							{
								path: "src/file.ts",
								whyRelevant: "supports the claim",
								diff: { base: " ", path: "src/file.ts" },
							},
						],
					}),
				]),
			/Review reference diff base is required: card/,
		);
		for (const path of ["/src/file.ts", "src/../file.ts"]) {
			assert.throws(
				() =>
					normalizeReviewCards([
						card({
							id: "card",
							references: [
								{
									path: "src/file.ts",
									whyRelevant: "supports the claim",
									diff: { base: "main", path },
								},
							],
						}),
					]),
				/Review reference diff path must be repo-relative: card/,
			);
		}
		for (const diff of [
			{ base: "--output=/tmp/file" },
			{ base: "main", head: "--cached" },
			{ base: "main..feature" },
			{ base: "main", head: "feature branch" },
		]) {
			assert.throws(
				() =>
					normalizeReviewCards([
						card({
							id: "card",
							references: [{ path: "src/file.ts", whyRelevant: "supports the claim", diff }],
						}),
					]),
				/Review reference diff (base|head) must be a simple revision, not an option or range: card/,
			);
		}
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [
							{
								path: "src/file.ts",
								whyRelevant: "supports the claim",
								diff: { base: "main", lineStart: 4, lineEnd: 3 },
							},
						],
					}),
				]),
			/Review reference diff lineEnd must be greater than or equal to lineStart: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [
							{
								path: "src/file.ts",
								whyRelevant: "supports the claim",
								diff: { base: "main", contextLines: -1 },
							},
						],
					}),
				]),
			/Review reference diff contextLines must be a non-negative integer no greater than 50: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [
							{
								path: "src/file.ts",
								whyRelevant: "supports the claim",
								diff: { base: "main", contextLines: 51 },
							},
						],
					}),
				]),
			/Review reference diff contextLines must be a non-negative integer no greater than 50: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [
							{
								path: "src/file.ts",
								whyRelevant: "supports the claim",
								diff: { base: "main", lineStart: 1.5 },
							},
						],
					}),
				]),
			/Review reference diff lineStart must be a positive integer: card/,
		);
	});

	it("rejects invalid references", () => {
		assert.throws(
			() =>
				normalizeReviewCards([card({ id: "card", references: [{ path: " ", whyRelevant: "supports the claim" }] })]),
			/Review reference path is required: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({ id: "card", references: [{ path: "src/file.ts", whyRelevant: " ", lineStart: 2 }] }),
				]),
			/Review reference whyRelevant is required: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({
						id: "card",
						references: [{ path: "src/file.ts", whyRelevant: "supports the claim", lineStart: 4, lineEnd: 3 }],
					}),
				]),
			/Review reference lineEnd must be greater than or equal to lineStart: card/,
		);
		assert.throws(
			() =>
				normalizeReviewCards([
					card({ id: "card", references: [{ path: "../src/file.ts", whyRelevant: "supports the claim" }] }),
				]),
			/Review reference path must be repo-relative: card/,
		);
	});
});

describe("normalizeReviewPacket", () => {
	it("normalizes target metadata, source context, and cards", () => {
		const packet: ReviewPacket = {
			target: {
				kind: "pr",
				prNumber: 12,
				branch: " feature/review ",
				base: " main ",
				headSha: " abc123 ",
			},
			source: {
				sessionId: " session-1 ",
				worktreeLabel: " wt-label ",
				goal: " Review the PR ",
			},
			cards: [card({ id: "risk", kind: "risk" }), card({ id: "orientation", kind: "orientation" })],
		};

		const normalized = normalizeReviewPacket(packet);

		assert.deepEqual(normalized.target, {
			kind: "pr",
			prNumber: 12,
			branch: "feature/review",
			base: "main",
			headSha: "abc123",
		});
		assert.deepEqual(normalized.source, {
			sessionId: "session-1",
			worktreeLabel: "wt-label",
			goal: "Review the PR",
		});
		assert.deepEqual(
			normalized.cards.map((item) => item.id),
			["orientation", "risk"],
		);
	});

	it("rejects incomplete target metadata", () => {
		assert.throws(
			() =>
				normalizeReviewPacket({
					target: { kind: "branch", branch: " ", base: "main" },
					cards: [card({ id: "orientation", kind: "orientation" })],
				}),
			/Review target branch is required/,
		);
		assert.throws(
			() =>
				normalizeReviewPacket({
					target: { kind: "branch", branch: "feature", base: " " },
					cards: [card({ id: "orientation", kind: "orientation" })],
				}),
			/Review target base is required/,
		);
		for (const prNumber of [undefined, 0, -1, 1.5]) {
			assert.throws(
				() =>
					normalizeReviewPacket({
						target: { kind: "pr", prNumber, branch: "feature", base: "main" },
						cards: [card({ id: "orientation", kind: "orientation" })],
					}),
				/Review target prNumber is required for PR reviews/,
			);
		}
	});

	it("normalizes whitespace-only source fields to undefined", () => {
		const normalized = normalizeReviewPacket({
			target: { kind: "branch", branch: "feature", base: "main" },
			source: { sessionId: " ", worktreeLabel: " ", goal: " " },
			cards: [card({ id: "orientation", kind: "orientation" })],
		});

		assert.deepEqual(normalized.source, {
			sessionId: undefined,
			worktreeLabel: undefined,
			goal: undefined,
		});
	});
});

describe("feedback helpers", () => {
	it("identifies feedback states that require text", () => {
		for (const category of ["needs_explanation", "question", "needs_code_change", "pending"] as const) {
			assert.equal(reviewFeedbackRequiresText(category), true);
		}
		assert.equal(reviewFeedbackRequiresText("approved"), false);
		assert.equal(reviewFeedbackRequiresText("skip"), false);
	});

	it("formats feedback category labels", () => {
		assert.equal(reviewFeedbackCategoryLabel("needs_code_change"), "Needs code change");
		assert.equal(reviewFeedbackCategoryLabel("pending"), "Pending");
	});
});

describe("consolidateReviewFeedback", () => {
	it("groups feedback by card and category in first-seen order", () => {
		const feedback: ReviewFeedback[] = [
			{ cardId: " intro ", category: "question", text: " Why this shape? " },
			{ cardId: "intro", category: "question", text: " Can we link the issue? " },
			{ cardId: "intro", category: "approved" },
			{ cardId: "risk", category: "needs_code_change", text: " Add a guard. " },
			{ cardId: "intro", category: "skip" },
		];

		assert.deepEqual(consolidateReviewFeedback(feedback), [
			{
				cardId: "intro",
				category: "question",
				texts: ["Why this shape?", "Can we link the issue?"],
			},
			{ cardId: "intro", category: "approved", texts: [] },
			{ cardId: "risk", category: "needs_code_change", texts: ["Add a guard."] },
			{ cardId: "intro", category: "skip", texts: [] },
		]);
	});

	it("requires text for non-approved and non-skip feedback states", () => {
		for (const category of ["needs_explanation", "question", "needs_code_change", "pending"] as const) {
			assert.throws(
				() => consolidateReviewFeedback([{ cardId: "card", category, text: " " }]),
				new RegExp(`Review feedback text is required for ${category}: card`),
			);
		}
	});

	it("allows approved and skip states without text but keeps optional text when present", () => {
		assert.deepEqual(
			consolidateReviewFeedback([
				{ cardId: "card", category: "approved" },
				{ cardId: "card", category: "skip", text: " Not relevant to this review. " },
			]),
			[
				{ cardId: "card", category: "approved", texts: [] },
				{ cardId: "card", category: "skip", texts: ["Not relevant to this review."] },
			],
		);
	});

	it("rejects feedback without a card id", () => {
		assert.throws(
			() => consolidateReviewFeedback([{ cardId: " ", category: "question", text: "What changed?" }]),
			/Review feedback cardId is required/,
		);
	});
});
