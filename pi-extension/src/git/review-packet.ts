import { type Static, Type } from "@sinclair/typebox";

export const ReviewTargetKindSchema = Type.Union([Type.Literal("pr"), Type.Literal("branch")]);
export type ReviewTargetKind = Static<typeof ReviewTargetKindSchema>;

export const ReviewTargetSchema = Type.Object({
	kind: ReviewTargetKindSchema,
	prNumber: Type.Optional(Type.Number()),
	branch: Type.String(),
	base: Type.String(),
	headSha: Type.Optional(Type.String()),
});
export type ReviewTarget = Static<typeof ReviewTargetSchema>;

export const ReviewSourceContextSchema = Type.Object({
	sessionId: Type.Optional(Type.String()),
	worktreeLabel: Type.Optional(Type.String()),
	goal: Type.Optional(Type.String()),
});
export type ReviewSourceContext = Static<typeof ReviewSourceContextSchema>;

export const ReviewCardKindSchema = Type.Union([
	Type.Literal("orientation"),
	Type.Literal("architecture"),
	Type.Literal("walkthrough"),
	Type.Literal("decision"),
	Type.Literal("diff-evidence"),
	Type.Literal("validation"),
	Type.Literal("risk"),
	Type.Literal("open-question"),
]);
export type ReviewCardKind = Static<typeof ReviewCardKindSchema>;

export const ReviewReferenceSchema = Type.Object({
	path: Type.String(),
	lineStart: Type.Optional(Type.Number()),
	lineEnd: Type.Optional(Type.Number()),
	commit: Type.Optional(Type.String()),
	quote: Type.Optional(Type.String()),
	whyRelevant: Type.String(),
});
export type ReviewReference = Static<typeof ReviewReferenceSchema>;

export const ReviewCardSchema = Type.Object({
	id: Type.String(),
	kind: ReviewCardKindSchema,
	title: Type.String(),
	body: Type.String(),
	references: Type.Optional(Type.Array(ReviewReferenceSchema)),
});
export type ReviewCard = Static<typeof ReviewCardSchema>;

export const ReviewPacketSchema = Type.Object({
	target: ReviewTargetSchema,
	source: Type.Optional(ReviewSourceContextSchema),
	cards: Type.Array(ReviewCardSchema),
});
export type ReviewPacket = Static<typeof ReviewPacketSchema>;

export const ReviewFeedbackCategorySchema = Type.Union([
	Type.Literal("approved"),
	Type.Literal("needs_explanation"),
	Type.Literal("question"),
	Type.Literal("needs_code_change"),
	Type.Literal("skip"),
	Type.Literal("pending"),
]);
export type ReviewFeedbackCategory = Static<typeof ReviewFeedbackCategorySchema>;

export const ReviewFeedbackSchema = Type.Object({
	cardId: Type.String(),
	category: ReviewFeedbackCategorySchema,
	text: Type.Optional(Type.String()),
});
export type ReviewFeedback = Static<typeof ReviewFeedbackSchema>;

export const ConsolidatedReviewFeedbackSchema = Type.Object({
	cardId: Type.String(),
	category: ReviewFeedbackCategorySchema,
	texts: Type.Array(Type.String()),
});
export type ConsolidatedReviewFeedback = Static<typeof ConsolidatedReviewFeedbackSchema>;

export const REVIEW_CARD_KIND_ORDER: readonly ReviewCardKind[] = [
	"orientation",
	"architecture",
	"walkthrough",
	"decision",
	"diff-evidence",
	"validation",
	"risk",
	"open-question",
] as const;

const CARD_KIND_RANK = new Map<ReviewCardKind, number>(REVIEW_CARD_KIND_ORDER.map((kind, index) => [kind, index]));

function trimmedOptional(value: string | undefined): string | undefined {
	const trimmed = value?.trim();
	return trimmed ? trimmed : undefined;
}

function normalizeReference(reference: ReviewReference, cardId: string): ReviewReference {
	const path = reference.path.trim();
	const whyRelevant = reference.whyRelevant.trim();

	if (!path) throw new Error(`Review reference path is required: ${cardId}`);
	if (!whyRelevant) throw new Error(`Review reference whyRelevant is required: ${cardId}`);
	if (reference.lineStart !== undefined && reference.lineStart < 1) {
		throw new Error(`Review reference lineStart must be positive: ${cardId}`);
	}
	if (reference.lineEnd !== undefined && reference.lineEnd < 1) {
		throw new Error(`Review reference lineEnd must be positive: ${cardId}`);
	}
	if (reference.lineStart !== undefined && reference.lineEnd !== undefined && reference.lineEnd < reference.lineStart) {
		throw new Error(`Review reference lineEnd must be greater than or equal to lineStart: ${cardId}`);
	}

	return {
		path,
		lineStart: reference.lineStart,
		lineEnd: reference.lineEnd,
		commit: trimmedOptional(reference.commit),
		quote: trimmedOptional(reference.quote),
		whyRelevant,
	};
}

function normalizeCard(card: ReviewCard): ReviewCard {
	const id = card.id.trim();
	return {
		id,
		kind: card.kind,
		title: card.title.trim(),
		body: card.body.trim(),
		references: card.references?.map((reference) => normalizeReference(reference, id || "unknown")),
	};
}

export function normalizeReviewCards(cards: readonly ReviewCard[]): ReviewCard[] {
	const seen = new Set<string>();
	return cards
		.map((card, index) => ({ card: normalizeCard(card), index }))
		.map((entry) => {
			if (!entry.card.id) throw new Error("Review card id is required.");
			if (seen.has(entry.card.id)) throw new Error(`Duplicate review card id: ${entry.card.id}`);
			seen.add(entry.card.id);
			if (!entry.card.title) throw new Error(`Review card title is required: ${entry.card.id}`);
			if (!entry.card.body) throw new Error(`Review card body is required: ${entry.card.id}`);
			return entry;
		})
		.sort((left, right) => {
			const leftRank = CARD_KIND_RANK.get(left.card.kind) ?? Number.MAX_SAFE_INTEGER;
			const rightRank = CARD_KIND_RANK.get(right.card.kind) ?? Number.MAX_SAFE_INTEGER;
			return leftRank - rightRank || left.index - right.index;
		})
		.map((entry) => entry.card);
}

export function normalizeReviewPacket(packet: ReviewPacket): ReviewPacket {
	const branch = packet.target.branch.trim();
	const base = packet.target.base.trim();
	const prNumber = packet.target.prNumber;

	if (!branch) throw new Error("Review target branch is required.");
	if (!base) throw new Error("Review target base is required.");
	if (packet.target.kind === "pr" && (!Number.isInteger(prNumber) || prNumber === undefined || prNumber < 1)) {
		throw new Error("Review target prNumber is required for PR reviews.");
	}

	return {
		target: {
			kind: packet.target.kind,
			prNumber,
			branch,
			base,
			headSha: trimmedOptional(packet.target.headSha),
		},
		source: packet.source
			? {
					sessionId: trimmedOptional(packet.source.sessionId),
					worktreeLabel: trimmedOptional(packet.source.worktreeLabel),
					goal: trimmedOptional(packet.source.goal),
				}
			: undefined,
		cards: normalizeReviewCards(packet.cards),
	};
}

function requiresFeedbackText(category: ReviewFeedbackCategory): boolean {
	return category !== "approved" && category !== "skip";
}

function feedbackKey(cardId: string, category: ReviewFeedbackCategory): string {
	return `${cardId}\u0000${category}`;
}

export function consolidateReviewFeedback(feedback: readonly ReviewFeedback[]): ConsolidatedReviewFeedback[] {
	const groups = new Map<string, ConsolidatedReviewFeedback>();
	const order: string[] = [];

	for (const item of feedback) {
		const cardId = item.cardId.trim();
		if (!cardId) throw new Error("Review feedback cardId is required.");

		const text = item.text?.trim();
		if (requiresFeedbackText(item.category) && !text) {
			throw new Error(`Review feedback text is required for ${item.category}: ${cardId}`);
		}

		const key = feedbackKey(cardId, item.category);
		let group = groups.get(key);
		if (!group) {
			group = { cardId, category: item.category, texts: [] };
			groups.set(key, group);
			order.push(key);
		}
		if (text) group.texts.push(text);
	}

	return order.map((key) => {
		const group = groups.get(key);
		if (!group) throw new Error(`Missing review feedback group: ${key}`);
		return { cardId: group.cardId, category: group.category, texts: [...group.texts] };
	});
}
