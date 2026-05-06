/**
 * Review packet walkthrough — context-first card review with per-card feedback.
 *
 * This TUI is intentionally read-only for repo/GitHub state. It only displays
 * normalized packet cards and collects structured reviewer feedback.
 */

import type { ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import {
	Container,
	Editor,
	type EditorTheme,
	getKeybindings,
	matchesKey,
	Spacer,
	Text,
	truncateToWidth,
	visibleWidth,
} from "@mariozechner/pi-tui";
import {
	type ConsolidatedReviewFeedback,
	consolidateReviewFeedback,
	type ReviewCard,
	type ReviewFeedback,
	type ReviewFeedbackCategory,
	type ReviewReference,
	reviewFeedbackCategoryLabel,
	reviewFeedbackRequiresText,
} from "./review-packet.ts";
import type { DisplayReviewCard, DisplayReviewPacket, DisplayReviewReference } from "./review-packet-diff.ts";

export interface ReviewPacketReviewResult {
	cancelled: boolean;
	feedback: ConsolidatedReviewFeedback[];
}

interface CardFeedbackDraft {
	category: ReviewFeedbackCategory;
	text: string | null;
}

interface CardGroup {
	kind: ReviewCard["kind"];
	cards: DisplayReviewCard[];
}

const NAV_KEYS = [
	"tui.editor.cursorUp",
	"tui.editor.cursorDown",
	"tui.editor.cursorLeft",
	"tui.editor.cursorRight",
	"tui.editor.cursorWordLeft",
	"tui.editor.cursorWordRight",
	"tui.editor.cursorLineStart",
	"tui.editor.cursorLineEnd",
	"tui.editor.pageUp",
	"tui.editor.pageDown",
] as const;

export const REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH = 96;

const REVIEW_PACKET_PANEL_GAP = 2;
const CARD_INSERTION_MARKER = "\uE000basecamp-review-packet-card\uE000";
const FEEDBACK_INSERTION_MARKER = "\uE000basecamp-review-packet-feedback\uE000";

export interface RenderReviewCardContentOptions {
	width: number;
	feedbackCategoryLabel?: string;
}

function stripInsertionMarkers(line: string): string {
	return line.replaceAll(CARD_INSERTION_MARKER, "").replaceAll(FEEDBACK_INSERTION_MARKER, "");
}

function isNavKey(data: string): boolean {
	const kb = getKeybindings();
	return NAV_KEYS.some((key) => kb.matches(data, key));
}

function kindLabel(kind: ReviewCard["kind"]): string {
	return kind
		.split("-")
		.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
		.join(" ");
}

function cardMarker(draft: CardFeedbackDraft | undefined, theme: Theme): string {
	if (!draft || (draft.category === "pending" && !draft.text)) return theme.fg("muted", "☐");

	let marker: string;
	switch (draft.category) {
		case "approved":
			marker = theme.fg("success", "✓");
			break;
		case "skip":
			marker = theme.fg("dim", "–");
			break;
		case "question":
			marker = theme.fg("warning", "?");
			break;
		case "needs_explanation":
			marker = theme.fg("warning", "!");
			break;
		case "needs_code_change":
			marker = theme.fg("error", "★");
			break;
		case "pending":
			marker = theme.fg("muted", "☐");
			break;
	}

	const note = draft.text ? theme.fg("dim", " 📝") : "";
	return `${marker}${note}`;
}

function groupCardsByKind(cards: readonly DisplayReviewCard[]): CardGroup[] {
	const groups: CardGroup[] = [];
	const byKind = new Map<ReviewCard["kind"], CardGroup>();

	for (const card of cards) {
		let group = byKind.get(card.kind);
		if (!group) {
			group = { kind: card.kind, cards: [] };
			byKind.set(card.kind, group);
			groups.push(group);
		}
		group.cards.push(card);
	}

	return groups;
}

function renderListView(
	groups: readonly CardGroup[],
	drafts: Map<string, CardFeedbackDraft>,
	groupPositions: Map<ReviewCard["kind"], number>,
	selected: number,
	theme: Theme,
): string[] {
	const lines: string[] = [];

	for (let i = 0; i < groups.length; i++) {
		const group = groups[i]!;
		const currentIdx = Math.min(groupPositions.get(group.kind) ?? 0, group.cards.length - 1);
		const card = group.cards[currentIdx]!;
		const cursor = i === selected ? theme.fg("accent", "▸") : " ";
		const marker = cardMarker(drafts.get(card.id), theme);
		const header = kindLabel(group.kind);
		const label = i === selected ? theme.fg("accent", theme.bold(header)) : theme.bold(header);
		const preview = card.body.length > 48 ? `${card.body.slice(0, 48)}…` : card.body;
		const count = group.cards.length === 1 ? "1 card" : `${currentIdx + 1} of ${group.cards.length}`;
		lines.push(
			`${cursor} ${marker} ${label}  ${theme.fg("dim", count)}  ${theme.fg("dim", card.title)}  ${theme.fg("dim", preview)}`,
		);
	}

	return lines;
}

function formatReferenceLocation(reference: ReviewReference, index: number): string {
	const range =
		reference.lineStart === undefined
			? ""
			: reference.lineEnd === undefined || reference.lineEnd === reference.lineStart
				? `:${reference.lineStart}`
				: `:${reference.lineStart}-${reference.lineEnd}`;
	const commit = reference.commit ? ` @ ${reference.commit}` : "";
	return `${index + 1}. ${reference.path}${range}${commit}`;
}

function renderProseLines(card: DisplayReviewCard, feedbackCategoryLabel: string): string[] {
	return [
		card.title,
		`Kind: ${kindLabel(card.kind)}`,
		`State: ${feedbackCategoryLabel}`,
		"",
		"Review notes",
		card.body,
	];
}

function renderReferenceEvidence(reference: DisplayReviewReference, index: number): string[] {
	const lines = [formatReferenceLocation(reference, index), `Why this matters: ${reference.whyRelevant}`];

	if (reference.quote) {
		lines.push("Quote:", "```");
		lines.push(...reference.quote.replace(/\r\n?/g, "\n").split("\n"));
		lines.push("```");
	}

	if (reference.resolvedDiff) {
		const resolvedDiff = reference.resolvedDiff;
		lines.push(`Resolved diff status: ${resolvedDiff.status}${resolvedDiff.truncated ? " (truncated)" : ""}`);
		if (resolvedDiff.message) lines.push(`Resolved diff message: ${resolvedDiff.message}`);
		if (resolvedDiff.text) {
			lines.push("Resolved diff:", "```");
			lines.push(...resolvedDiff.text.replace(/\r\n?/g, "\n").split("\n"));
			lines.push("```");
		}
	}

	return lines;
}

function renderEvidenceLines(card: DisplayReviewCard): string[] {
	const lines: string[] = [];
	const references = card.references ?? [];
	for (let i = 0; i < references.length; i++) {
		if (lines.length > 0) lines.push("");
		lines.push(...renderReferenceEvidence(references[i]!, i));
	}
	return lines;
}

function hasResolvedDiffEvidence(card: DisplayReviewCard): boolean {
	return Boolean(card.references?.some((reference) => Boolean(reference.resolvedDiff)));
}

export interface ReviewCardContentSections {
	proseLines: string[];
	evidenceLines: string[];
	sideBySideEligible: boolean;
}

export interface ComposeReviewCardPanelsOptions {
	width: number;
	gap?: number;
}

interface ReviewCardPanelLayout {
	proseWidth: number;
	evidenceWidth: number;
	gap: number;
}

function getReviewCardPanelLayout(width: number, gapOption?: number): ReviewCardPanelLayout {
	const normalizedWidth = Math.max(1, width);
	const gap = Math.max(0, gapOption ?? REVIEW_PACKET_PANEL_GAP);
	const availableWidth = Math.max(1, normalizedWidth - gap);
	const proseWidth = Math.max(1, Math.floor(availableWidth / 2));
	const evidenceWidth = Math.max(1, availableWidth - proseWidth);
	return { proseWidth, evidenceWidth, gap };
}

export function getReviewCardContentSections(
	card: DisplayReviewCard,
	options: RenderReviewCardContentOptions,
): ReviewCardContentSections {
	const feedbackCategoryLabel = options.feedbackCategoryLabel ?? reviewFeedbackCategoryLabel("pending");
	const proseLines = renderProseLines(card, feedbackCategoryLabel);
	const evidenceLines = renderEvidenceLines(card);
	const sideBySideEligible =
		evidenceLines.length > 0 && options.width >= REVIEW_PACKET_SIDE_BY_SIDE_MIN_WIDTH && hasResolvedDiffEvidence(card);

	return { proseLines, evidenceLines, sideBySideEligible };
}

function fitLineToWidth(line: string, width: number): string {
	if (width <= 0) return "";
	const fitted = visibleWidth(line) > width ? truncateToWidth(line, width, "") : line;
	return `${fitted}${" ".repeat(Math.max(0, width - visibleWidth(fitted)))}`;
}

export function composeReviewCardPanels(
	prosePanelLines: readonly string[],
	evidencePanelLines: readonly string[],
	options: ComposeReviewCardPanelsOptions,
): string[] {
	const width = Math.max(1, options.width);
	const { proseWidth, evidenceWidth, gap } = getReviewCardPanelLayout(width, options.gap);
	const gapText = " ".repeat(gap);
	const maxLines = Math.max(prosePanelLines.length, evidencePanelLines.length);
	const lines: string[] = [];

	for (let i = 0; i < maxLines; i++) {
		const left = fitLineToWidth(prosePanelLines[i] ?? "", proseWidth);
		const right = fitLineToWidth(evidencePanelLines[i] ?? "", evidenceWidth);
		lines.push(truncateToWidth(`${left}${gapText}${right}`.trimEnd(), width, ""));
	}

	return lines;
}

export function renderReviewCardContent(card: DisplayReviewCard, options: RenderReviewCardContentOptions): string[] {
	const { proseLines, evidenceLines } = getReviewCardContentSections(card, options);
	if (evidenceLines.length === 0) return proseLines;
	return [...proseLines, "", "Evidence", "", ...evidenceLines];
}

function draftFor(cardId: string, drafts: Map<string, CardFeedbackDraft>): CardFeedbackDraft {
	return drafts.get(cardId) ?? { category: "pending", text: null };
}

function setDraft(
	cardId: string,
	drafts: Map<string, CardFeedbackDraft>,
	category: ReviewFeedbackCategory,
	text: string | null,
): void {
	drafts.set(cardId, { category, text: text?.trim() || null });
}

function isCardReviewed(card: DisplayReviewCard, drafts: Map<string, CardFeedbackDraft>): boolean {
	const draft = drafts.get(card.id);
	if (!draft || draft.category === "pending") return false;
	return !reviewFeedbackRequiresText(draft.category) || Boolean(draft.text);
}

function buildReviewFeedback(
	cards: readonly DisplayReviewCard[],
	drafts: Map<string, CardFeedbackDraft>,
): ReviewFeedback[] {
	const feedback: ReviewFeedback[] = [];

	for (const card of cards) {
		const draft = drafts.get(card.id);
		if (!draft) continue;
		if (reviewFeedbackRequiresText(draft.category) && !draft.text) continue;
		feedback.push({ cardId: card.id, category: draft.category, text: draft.text ?? undefined });
	}

	return feedback;
}

function consolidatedResult(
	cancelled: boolean,
	cards: readonly DisplayReviewCard[],
	drafts: Map<string, CardFeedbackDraft>,
): ReviewPacketReviewResult {
	return { cancelled, feedback: consolidateReviewFeedback(buildReviewFeedback(cards, drafts)) };
}

export async function showReviewPacket(
	packet: DisplayReviewPacket,
	ctx: ExtensionContext,
): Promise<ReviewPacketReviewResult> {
	const normalized = packet;
	const cards = normalized.cards;
	const groups = groupCardsByKind(cards);
	const groupPositions = new Map<ReviewCard["kind"], number>();
	const drafts = new Map<string, CardFeedbackDraft>();
	let lastSelected = 0;

	if (cards.length === 0) return consolidatedResult(false, cards, drafts);

	while (true) {
		const selection = await ctx.ui.custom<number | "submit" | "cancel">((_tui, theme, _kb, done) => {
			let selected = Math.min(lastSelected, groups.length - 1);
			const target =
				normalized.target.kind === "pr"
					? `PR #${normalized.target.prNumber}  ${normalized.target.branch} → ${normalized.target.base}`
					: `${normalized.target.branch} → ${normalized.target.base}`;
			const defaultHint = theme.fg(
				"dim",
				"[↑↓: Navigate]  [Space/Enter: Drill in]  [s: Submit feedback]  [Esc: Cancel]",
			);
			const border = new DynamicBorder((s: string) => theme.fg("border", s));
			const header = new Text(theme.fg("accent", theme.bold("Review Packet")), 1, 0);
			const targetLine = new Text(`${theme.fg("dim", "Target")}  ${target}`, 1, 0);
			const hint = new Text(defaultHint, 1, 0);
			const listText = new Text("", 0, 0);

			const container = new Container();
			container.addChild(border);
			container.addChild(header);
			container.addChild(targetLine);
			container.addChild(new Spacer(1));
			container.addChild(listText);
			container.addChild(new Spacer(1));
			container.addChild(hint);
			container.addChild(border);

			return {
				render: (width: number) => {
					listText.setText(renderListView(groups, drafts, groupPositions, selected, theme).join("\n"));
					return container.render(width);
				},
				invalidate: () => container.invalidate(),
				handleInput: (data: string) => {
					hint.setText(defaultHint);
					if (matchesSelectCancel(data)) {
						done("cancel");
					} else if (data === "s" || data === "S") {
						const unreviewedCards = cards.filter((card) => !isCardReviewed(card, drafts));
						const firstUnreviewed = unreviewedCards[0];
						if (firstUnreviewed) {
							const groupIndex = groups.findIndex((group) => group.kind === firstUnreviewed.kind);
							const group = groupIndex >= 0 ? groups[groupIndex] : undefined;
							if (group) {
								selected = groupIndex;
								groupPositions.set(
									group.kind,
									Math.max(
										0,
										group.cards.findIndex((card) => card.id === firstUnreviewed.id),
									),
								);
							}
							hint.setText(
								theme.fg(
									"warning",
									`${unreviewedCards.length} card${unreviewedCards.length === 1 ? "" : "s"} still pending review`,
								),
							);
							container.invalidate();
							return;
						}
						done("submit");
					} else if (data === " " || matchesInputSubmit(data)) {
						done(selected);
					} else if (matchesMoveUp(data)) {
						if (selected > 0) {
							selected--;
							container.invalidate();
						}
					} else if (matchesMoveDown(data)) {
						if (selected < groups.length - 1) {
							selected++;
							container.invalidate();
						}
					}
				},
			};
		});

		if (selection === "submit") return consolidatedResult(false, cards, drafts);
		if (selection === "cancel") return consolidatedResult(true, cards, drafts);

		lastSelected = selection;
		const group = groups[selection]!;
		const startIndex = Math.min(groupPositions.get(group.kind) ?? 0, group.cards.length - 1);
		const selectedCardIndex = await showCardDrillDown(group, drafts, startIndex, ctx);
		groupPositions.set(group.kind, selectedCardIndex);
	}
}

function matchesInputSubmit(data: string): boolean {
	return getKeybindings().matches(data, "tui.input.submit");
}

function matchesSelectCancel(data: string): boolean {
	return getKeybindings().matches(data, "tui.select.cancel");
}

function matchesInputTab(data: string): boolean {
	return getKeybindings().matches(data, "tui.input.tab");
}

function matchesMoveUp(data: string): boolean {
	return matchesKey(data, "up");
}

function matchesMoveDown(data: string): boolean {
	return matchesKey(data, "down");
}

async function showCardDrillDown(
	group: CardGroup,
	drafts: Map<string, CardFeedbackDraft>,
	startIndex: number,
	ctx: ExtensionContext,
): Promise<number> {
	let currentIdx = startIndex;
	await ctx.ui.custom<void>((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text("", 1, 0);
		const cardLabel = new Text(`${theme.fg("dim", "Card")}${CARD_INSERTION_MARKER}`, 0, 0);
		const feedbackLabel = new Text("", 0, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};

		const viewer = new Editor(tui, editorTheme, { paddingX: 0 });
		const proseViewer = new Editor(tui, editorTheme, { paddingX: 0 });
		const evidenceViewer = new Editor(tui, editorTheme, { paddingX: 0 });
		type ViewerState = { state: { cursorLine: number; cursorCol: number }; scrollOffset: number };
		const viewerState = viewer as unknown as ViewerState;
		const proseViewerState = proseViewer as unknown as ViewerState;
		const evidenceViewerState = evidenceViewer as unknown as ViewerState;
		viewer.focused = true;
		viewer.disableSubmit = true;
		proseViewer.focused = false;
		proseViewer.disableSubmit = true;
		evidenceViewer.focused = false;
		evidenceViewer.disableSubmit = true;

		const feedback = new Editor(tui, editorTheme, { paddingX: 0 });
		feedback.focused = false;

		let feedbackFocused = false;
		let pendingCategory: ReviewFeedbackCategory | null = null;
		let statusMessage: string | null = null;
		let viewerDirty = true;
		let renderedCardId: string | null = null;
		let renderedContentWidth = 0;
		let renderedSideBySide = false;

		function resetViewerState(state: ViewerState): void {
			state.state.cursorLine = 0;
			state.state.cursorCol = 0;
			state.scrollOffset = 0;
		}

		function resetViewerScroll(): void {
			resetViewerState(viewerState);
			resetViewerState(proseViewerState);
			resetViewerState(evidenceViewerState);
		}

		function setReviewViewersFocused(focused: boolean): void {
			viewer.focused = focused;
			proseViewer.focused = false;
			evidenceViewer.focused = false;
		}

		feedback.onSubmit = (value: string) => {
			const card = group.cards[currentIdx]!;
			const current = draftFor(card.id, drafts);
			const category = pendingCategory ?? current.category;
			const text = value.trim();
			if (reviewFeedbackRequiresText(category) && !text) {
				statusMessage = `${reviewFeedbackCategoryLabel(category)} requires feedback text.`;
				updateHint();
				container.invalidate();
				return;
			}

			setDraft(card.id, drafts, category, text || null);
			pendingCategory = null;
			feedbackFocused = false;
			feedback.focused = false;
			setReviewViewersFocused(true);
			statusMessage = null;
			updateViewer();
			updateHint();
			container.invalidate();
		};

		function updateViewer(): void {
			header.setText(
				`${theme.fg("accent", theme.bold(kindLabel(group.kind)))}  ${theme.fg("dim", `${currentIdx + 1} of ${group.cards.length}`)}`,
			);
			viewerDirty = true;
		}

		function renderViewerContent(width: number): string[] {
			const card = group.cards[currentIdx]!;
			const contentWidth = Math.max(1, width);
			const sections = getReviewCardContentSections(card, {
				width: contentWidth,
				feedbackCategoryLabel: reviewFeedbackCategoryLabel(drafts.get(card.id)?.category ?? "pending"),
			});
			const cardChanged = renderedCardId !== card.id;
			const widthChanged = renderedContentWidth !== contentWidth;
			const layoutChanged = renderedSideBySide !== sections.sideBySideEligible;
			if (viewerDirty || cardChanged || widthChanged || layoutChanged) {
				if (sections.sideBySideEligible) {
					proseViewer.setText(sections.proseLines.join("\n"));
					evidenceViewer.setText(["Evidence", "", ...sections.evidenceLines].join("\n"));
				} else {
					viewer.setText(
						renderReviewCardContent(card, {
							width: contentWidth,
							feedbackCategoryLabel: reviewFeedbackCategoryLabel(drafts.get(card.id)?.category ?? "pending"),
						}).join("\n"),
					);
				}
				renderedCardId = card.id;
				renderedContentWidth = contentWidth;
				renderedSideBySide = sections.sideBySideEligible;
				viewerDirty = false;
				resetViewerScroll();
			}
			if (!sections.sideBySideEligible) return viewer.render(contentWidth);
			const { proseWidth, evidenceWidth, gap } = getReviewCardPanelLayout(contentWidth);
			return composeReviewCardPanels(proseViewer.render(proseWidth), evidenceViewer.render(evidenceWidth), {
				width: contentWidth,
				gap,
			});
		}

		function focusFeedback(message: string | null = null): void {
			const card = group.cards[currentIdx]!;
			statusMessage = message;
			feedbackFocused = true;
			feedback.focused = true;
			setReviewViewersFocused(false);
			feedback.setText(draftFor(card.id, drafts).text ?? "");
			updateHint();
			container.invalidate();
		}

		function chooseCategory(category: ReviewFeedbackCategory): void {
			const card = group.cards[currentIdx]!;
			const current = draftFor(card.id, drafts);
			statusMessage = null;
			if (reviewFeedbackRequiresText(category) && !current.text) {
				pendingCategory = category;
				focusFeedback(`${reviewFeedbackCategoryLabel(category)} requires feedback text.`);
				return;
			}
			pendingCategory = null;
			setDraft(card.id, drafts, category, current.text);
			updateViewer();
			updateHint();
			container.invalidate();
		}

		function updateHint(): void {
			const card = group.cards[currentIdx]!;
			const current = draftFor(card.id, drafts);
			const activeCategory = pendingCategory ?? current.category;
			const state = `${theme.fg("dim", "State")}  ${reviewFeedbackCategoryLabel(activeCategory)}`;
			const message = statusMessage ? `  ${theme.fg("warning", statusMessage)}` : "";
			if (feedbackFocused) {
				hint.setText(`${state}${message}\n${theme.fg("dim", "[Enter: Save]  [Esc: Clear/Back]")}`);
				feedbackLabel.setText(`${theme.fg("accent", "Feedback")}${FEEDBACK_INSERTION_MARKER}`);
			} else {
				const keys =
					"[←→: Navigate]  [a: Approve]  [e: Needs explanation]  [q: Question]  [c: Code change]  [k: Skip]  [Tab: Feedback]  [Esc: Back]";
				hint.setText(`${state}${message}\n${theme.fg("dim", keys)}`);
				const text = current.text;
				feedbackLabel.setText(
					text
						? `${theme.fg("dim", "Feedback")}\n${text}${FEEDBACK_INSERTION_MARKER}`
						: `${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[Tab]")}${FEEDBACK_INSERTION_MARKER}`,
				);
			}
		}

		function navigate(delta: number): void {
			const nextIdx = currentIdx + delta;
			if (nextIdx < 0 || nextIdx >= group.cards.length) return;
			currentIdx = nextIdx;
			pendingCategory = null;
			statusMessage = null;
			feedback.setText(draftFor(group.cards[currentIdx]!.id, drafts).text ?? "");
			updateViewer();
			updateHint();
			container.invalidate();
		}

		updateViewer();
		updateHint();

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(cardLabel);
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const lines = container.render(width);
				const cardIdx = lines.findIndex((line) => line.includes(CARD_INSERTION_MARKER));
				let feedbackIdx = lines.findIndex((line) => line.includes(FEEDBACK_INSERTION_MARKER));

				if (cardIdx >= 0) {
					const viewerLines = renderViewerContent(width - 2);
					lines.splice(cardIdx + 1, 0, ...viewerLines);
					if (feedbackIdx > cardIdx) feedbackIdx += viewerLines.length;
				}

				if (feedbackFocused && feedbackIdx >= 0) {
					const feedbackLines = feedback.render(width - 2);
					lines.splice(feedbackIdx + 1, 0, ...feedbackLines);
				}

				return lines.map(stripInsertionMarkers);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (feedbackFocused) {
					if (matchesSelectCancel(data)) {
						if (feedback.getText() !== "") {
							feedback.setText("");
						} else {
							feedbackFocused = false;
							feedback.focused = false;
							setReviewViewersFocused(true);
							pendingCategory = null;
							statusMessage = null;
							updateHint();
						}
						container.invalidate();
					} else {
						feedback.handleInput(data);
						container.invalidate();
					}
					return;
				}

				if (matchesKey(data, "left")) {
					navigate(-1);
					return;
				}
				if (matchesKey(data, "right")) {
					navigate(1);
					return;
				}

				if (isNavKey(data)) {
					if (renderedSideBySide) {
						proseViewer.handleInput(data);
						evidenceViewer.handleInput(data);
					} else {
						viewer.handleInput(data);
					}
					container.invalidate();
					return;
				}

				if (matchesSelectCancel(data)) {
					done(undefined);
				} else if (matchesInputTab(data)) {
					focusFeedback();
				} else if (data === "a" || data === "A") {
					chooseCategory("approved");
				} else if (data === "e" || data === "E") {
					chooseCategory("needs_explanation");
				} else if (data === "q" || data === "Q") {
					chooseCategory("question");
				} else if (data === "c" || data === "C") {
					chooseCategory("needs_code_change");
				} else if (data === "k" || data === "K") {
					chooseCategory("skip");
				}
			},
		};
	});
	return currentIdx;
}
