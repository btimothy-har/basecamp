/**
 * Review packet walkthrough — context-first card review with per-card feedback.
 *
 * This TUI is intentionally read-only for repo/GitHub state. It only displays
 * normalized packet cards and collects structured reviewer feedback.
 */

import type { ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import { Container, Editor, type EditorTheme, getKeybindings, matchesKey, Spacer, Text } from "@mariozechner/pi-tui";
import {
	type ConsolidatedReviewFeedback,
	consolidateReviewFeedback,
	normalizeReviewPacket,
	type ReviewCard,
	type ReviewFeedback,
	type ReviewFeedbackCategory,
	type ReviewPacket,
	type ReviewReference,
	reviewFeedbackCategoryLabel,
	reviewFeedbackRequiresText,
} from "./review-packet";

export interface ReviewPacketReviewResult {
	cancelled: boolean;
	feedback: ConsolidatedReviewFeedback[];
}

interface CardFeedbackDraft {
	category: ReviewFeedbackCategory;
	text: string | null;
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

const CARD_INSERTION_MARKER = "\uE000basecamp-review-packet-card\uE000";
const FEEDBACK_INSERTION_MARKER = "\uE000basecamp-review-packet-feedback\uE000";

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

function renderListView(
	cards: readonly ReviewCard[],
	drafts: Map<string, CardFeedbackDraft>,
	selected: number,
	theme: Theme,
): string[] {
	const lines: string[] = [];

	for (let i = 0; i < cards.length; i++) {
		const card = cards[i]!;
		const cursor = i === selected ? theme.fg("accent", "▸") : " ";
		const marker = cardMarker(drafts.get(card.id), theme);
		const title = i === selected ? theme.fg("accent", theme.bold(card.title)) : theme.bold(card.title);
		const preview = card.body.length > 48 ? `${card.body.slice(0, 48)}…` : card.body;
		lines.push(`${cursor} ${marker} ${title}  ${theme.fg("dim", kindLabel(card.kind))}  ${theme.fg("dim", preview)}`);
	}

	return lines;
}

function formatReference(reference: ReviewReference, index: number): string[] {
	const range =
		reference.lineStart === undefined
			? ""
			: reference.lineEnd === undefined || reference.lineEnd === reference.lineStart
				? `:${reference.lineStart}`
				: `:${reference.lineStart}-${reference.lineEnd}`;
	const commit = reference.commit ? ` @ ${reference.commit}` : "";
	const lines = [`${index + 1}. ${reference.path}${range}${commit}`, `   ${reference.whyRelevant}`];
	if (reference.quote) lines.push(`   “${reference.quote}”`);
	return lines;
}

function renderCardContent(card: ReviewCard, draft: CardFeedbackDraft | undefined): string[] {
	const lines: string[] = [];
	lines.push(card.title);
	lines.push(`Kind: ${kindLabel(card.kind)}`);
	lines.push(`State: ${reviewFeedbackCategoryLabel(draft?.category ?? "pending")}`);
	lines.push("");
	lines.push(card.body);

	if (card.references && card.references.length > 0) {
		lines.push("");
		lines.push("Supporting references / diff evidence");
		for (let i = 0; i < card.references.length; i++) {
			lines.push("");
			lines.push(...formatReference(card.references[i]!, i));
		}
	}

	return lines;
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

function buildReviewFeedback(cards: readonly ReviewCard[], drafts: Map<string, CardFeedbackDraft>): ReviewFeedback[] {
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
	cards: readonly ReviewCard[],
	drafts: Map<string, CardFeedbackDraft>,
): ReviewPacketReviewResult {
	return { cancelled, feedback: consolidateReviewFeedback(buildReviewFeedback(cards, drafts)) };
}

export async function showReviewPacket(packet: ReviewPacket, ctx: ExtensionContext): Promise<ReviewPacketReviewResult> {
	const normalized = normalizeReviewPacket(packet);
	const cards = normalized.cards;
	const drafts = new Map<string, CardFeedbackDraft>();
	let lastSelected = 0;

	if (cards.length === 0) return consolidatedResult(false, cards, drafts);

	while (true) {
		const selection = await ctx.ui.custom<number | "submit" | "cancel">((_tui, theme, _kb, done) => {
			let selected = Math.min(lastSelected, cards.length - 1);
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
					listText.setText(renderListView(cards, drafts, selected, theme).join("\n"));
					return container.render(width);
				},
				invalidate: () => container.invalidate(),
				handleInput: (data: string) => {
					hint.setText(defaultHint);
					if (matchesSelectCancel(data)) {
						done("cancel");
					} else if (data === "s" || data === "S") {
						done("submit");
					} else if (data === " " || matchesInputSubmit(data)) {
						done(selected);
					} else if (matchesMoveUp(data)) {
						if (selected > 0) {
							selected--;
							container.invalidate();
						}
					} else if (matchesMoveDown(data)) {
						if (selected < cards.length - 1) {
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
		await showCardDrillDown(cards[selection]!, cards, drafts, selection, ctx);
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
	card: ReviewCard,
	cards: readonly ReviewCard[],
	drafts: Map<string, CardFeedbackDraft>,
	index: number,
	ctx: ExtensionContext,
): Promise<void> {
	await ctx.ui.custom<void>((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text(
			`${theme.fg("accent", theme.bold("Review Card"))}  ${theme.fg("dim", `${index + 1} of ${cards.length}`)}`,
			1,
			0,
		);
		const cardLabel = new Text(`${theme.fg("dim", "Card")}${CARD_INSERTION_MARKER}`, 0, 0);
		const feedbackLabel = new Text("", 0, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};

		const viewer = new Editor(tui, editorTheme, { paddingX: 0 });
		viewer.setText(renderCardContent(card, drafts.get(card.id)).join("\n"));
		const viewerState = viewer as unknown as { state: { cursorLine: number; cursorCol: number }; scrollOffset: number };
		viewerState.state.cursorLine = 0;
		viewerState.state.cursorCol = 0;
		viewerState.scrollOffset = 0;
		viewer.focused = true;
		viewer.disableSubmit = true;

		const feedback = new Editor(tui, editorTheme, { paddingX: 0 });
		feedback.setText(draftFor(card.id, drafts).text ?? "");
		feedback.focused = false;

		let feedbackFocused = false;
		let pendingCategory: ReviewFeedbackCategory | null = null;
		let statusMessage: string | null = null;

		feedback.onSubmit = (value: string) => {
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
			viewer.focused = true;
			statusMessage = null;
			updateViewer();
			updateHint();
			container.invalidate();
		};

		function updateViewer(): void {
			viewer.setText(renderCardContent(card, drafts.get(card.id)).join("\n"));
			viewerState.state.cursorLine = 0;
			viewerState.state.cursorCol = 0;
			viewerState.scrollOffset = 0;
		}

		function focusFeedback(message: string | null = null): void {
			statusMessage = message;
			feedbackFocused = true;
			feedback.focused = true;
			viewer.focused = false;
			feedback.setText(draftFor(card.id, drafts).text ?? "");
			updateHint();
			container.invalidate();
		}

		function chooseCategory(category: ReviewFeedbackCategory): void {
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
			const current = draftFor(card.id, drafts);
			const activeCategory = pendingCategory ?? current.category;
			const state = `${theme.fg("dim", "State")}  ${reviewFeedbackCategoryLabel(activeCategory)}`;
			const message = statusMessage ? `  ${theme.fg("warning", statusMessage)}` : "";
			if (feedbackFocused) {
				hint.setText(`${state}${message}\n${theme.fg("dim", "[Enter: Save]  [Esc: Clear/Back]")}`);
				feedbackLabel.setText(`${theme.fg("accent", "Feedback")}${FEEDBACK_INSERTION_MARKER}`);
			} else {
				const keys =
					"[a: Approve]  [e: Needs explanation]  [q: Question]  [c: Code change]  [k: Skip]  [Tab: Feedback]  [Esc: Back]";
				hint.setText(`${state}${message}\n${theme.fg("dim", keys)}`);
				const text = current.text;
				feedbackLabel.setText(
					text
						? `${theme.fg("dim", "Feedback")}\n${text}${FEEDBACK_INSERTION_MARKER}`
						: `${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[Tab]")}${FEEDBACK_INSERTION_MARKER}`,
				);
			}
		}

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
					const viewerLines = viewer.render(width - 2);
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
							viewer.focused = true;
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

				if (isNavKey(data)) {
					viewer.handleInput(data);
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
}
