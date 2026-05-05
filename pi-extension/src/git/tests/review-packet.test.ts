import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	consolidateReviewFeedback,
	normalizeReviewCards,
	normalizeReviewPacket,
	type ReviewCard,
	type ReviewFeedback,
	type ReviewPacket,
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

	it("rejects duplicate or empty stable ids", () => {
		assert.throws(
			() => normalizeReviewCards([card({ id: "same" }), card({ id: " same ", title: "Other" })]),
			/Duplicate review card id: same/,
		);
		assert.throws(() => normalizeReviewCards([card({ id: " " })]), /Review card id is required/);
	});

	it("rejects invalid references", () => {
		assert.throws(
			() =>
				normalizeReviewCards([
					card({ id: "card", references: [{ path: " ", whyRelevant: "supports the claim" }] }),
				]),
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
		assert.throws(
			() =>
				normalizeReviewPacket({
					target: { kind: "pr", branch: "feature", base: "main" },
					cards: [card({ id: "orientation", kind: "orientation" })],
				}),
			/Review target prNumber is required for PR reviews/,
		);
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
