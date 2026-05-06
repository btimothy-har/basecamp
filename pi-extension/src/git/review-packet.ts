import { type Static, Type } from "@sinclair/typebox";

export const ReviewTargetKindSchema = Type.Union([Type.Literal("pr"), Type.Literal("branch")]);
export type ReviewTargetKind = Static<typeof ReviewTargetKindSchema>;

export const REVIEW_PACKET_LIMITS = {
	cards: 50,
	referencesPerCard: 20,
	shortText: 200,
	body: 50_000,
	quote: 5_000,
	diffContextLines: 50,
} as const;

export const ReviewTargetSchema = Type.Object({
	kind: ReviewTargetKindSchema,
	prNumber: Type.Optional(Type.Number()),
	branch: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	base: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	headSha: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
});
export type ReviewTarget = Static<typeof ReviewTargetSchema>;

export const ReviewSourceContextSchema = Type.Object({
	sessionId: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
	worktreeLabel: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
	goal: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.body })),
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

export const ReviewDiffReferenceSchema = Type.Object({
	base: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	head: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
	path: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
	lineStart: Type.Optional(Type.Number()),
	lineEnd: Type.Optional(Type.Number()),
	contextLines: Type.Optional(Type.Number({ maximum: REVIEW_PACKET_LIMITS.diffContextLines })),
});
export type ReviewDiffReference = Static<typeof ReviewDiffReferenceSchema>;

export const ReviewReferenceSchema = Type.Object({
	path: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	lineStart: Type.Optional(Type.Number()),
	lineEnd: Type.Optional(Type.Number()),
	commit: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText })),
	quote: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.quote })),
	diff: Type.Optional(ReviewDiffReferenceSchema),
	whyRelevant: Type.String({ maxLength: REVIEW_PACKET_LIMITS.body }),
});
export type ReviewReference = Static<typeof ReviewReferenceSchema>;

export const ReviewCardSchema = Type.Object({
	id: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	kind: ReviewCardKindSchema,
	title: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	body: Type.String({ maxLength: REVIEW_PACKET_LIMITS.body }),
	references: Type.Optional(Type.Array(ReviewReferenceSchema, { maxItems: REVIEW_PACKET_LIMITS.referencesPerCard })),
});
export type ReviewCard = Static<typeof ReviewCardSchema>;

export const ReviewPacketSchema = Type.Object({
	target: ReviewTargetSchema,
	source: Type.Optional(ReviewSourceContextSchema),
	cards: Type.Array(ReviewCardSchema, { maxItems: REVIEW_PACKET_LIMITS.cards }),
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
	cardId: Type.String({ maxLength: REVIEW_PACKET_LIMITS.shortText }),
	category: ReviewFeedbackCategorySchema,
	text: Type.Optional(Type.String({ maxLength: REVIEW_PACKET_LIMITS.body })),
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

function assertRepoRelativePath(path: string, label: string, cardId: string): void {
	if (path.startsWith("/") || path.split(/[\\/]+/).includes("..")) {
		throw new Error(`${label} must be repo-relative: ${cardId}`);
	}
}

function assertGitRevision(value: string, label: string, cardId: string): void {
	if (value.startsWith("-") || value.includes("..") || /\s/.test(value)) {
		throw new Error(`${label} must be a simple revision, not an option or range: ${cardId}`);
	}
}

function assertPositiveInteger(value: number | undefined, label: string, cardId: string): void {
	if (value !== undefined && (!Number.isInteger(value) || value < 1)) {
		throw new Error(`${label} must be a positive integer: ${cardId}`);
	}
}

function normalizeDiffReference(diff: ReviewDiffReference, cardId: string): ReviewDiffReference {
	const base = diff.base.trim();
	const head = trimmedOptional(diff.head);
	const path = trimmedOptional(diff.path);

	if (!base) throw new Error(`Review reference diff base is required: ${cardId}`);
	assertGitRevision(base, "Review reference diff base", cardId);
	if (head) assertGitRevision(head, "Review reference diff head", cardId);
	if (path) assertRepoRelativePath(path, "Review reference diff path", cardId);
	assertPositiveInteger(diff.lineStart, "Review reference diff lineStart", cardId);
	assertPositiveInteger(diff.lineEnd, "Review reference diff lineEnd", cardId);
	if (diff.lineStart !== undefined && diff.lineEnd !== undefined && diff.lineEnd < diff.lineStart) {
		throw new Error(`Review reference diff lineEnd must be greater than or equal to lineStart: ${cardId}`);
	}
	if (
		diff.contextLines !== undefined &&
		(!Number.isInteger(diff.contextLines) ||
			diff.contextLines < 0 ||
			diff.contextLines > REVIEW_PACKET_LIMITS.diffContextLines)
	) {
		throw new Error(
			`Review reference diff contextLines must be a non-negative integer no greater than ${REVIEW_PACKET_LIMITS.diffContextLines}: ${cardId}`,
		);
	}

	return {
		base,
		head,
		path,
		lineStart: diff.lineStart,
		lineEnd: diff.lineEnd,
		contextLines: diff.contextLines,
	};
}

function normalizeReference(reference: ReviewReference, cardId: string): ReviewReference {
	const path = reference.path.trim();
	const whyRelevant = reference.whyRelevant.trim();

	if (!path) throw new Error(`Review reference path is required: ${cardId}`);
	assertRepoRelativePath(path, "Review reference path", cardId);
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
		...(reference.diff ? { diff: normalizeDiffReference(reference.diff, cardId) } : {}),
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
	if (packet.target.kind === "pr" && (typeof prNumber !== "number" || !Number.isInteger(prNumber) || prNumber < 1)) {
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

export function reviewFeedbackRequiresText(category: ReviewFeedbackCategory): boolean {
	return category !== "approved" && category !== "skip";
}

export function reviewFeedbackCategoryLabel(category: ReviewFeedbackCategory): string {
	switch (category) {
		case "approved":
			return "Approved";
		case "needs_explanation":
			return "Needs explanation";
		case "question":
			return "Question";
		case "needs_code_change":
			return "Needs code change";
		case "skip":
			return "Skip";
		case "pending":
			return "Pending";
	}
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
		if (reviewFeedbackRequiresText(item.category) && !text) {
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
