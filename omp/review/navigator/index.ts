/**
 * The review navigator: a finding list that drills into a card carrying an optional user comment.
 *
 * Both views read comment text from the CommentStore and write it back only through card events —
 * the Editor is a buffer, never an authority. See model.ts for why that ownership matters.
 */

import type { ExtensionUIContext } from "@oh-my-pi/pi-coding-agent";
import { DynamicBorder, getSelectListTheme, getSymbolTheme } from "@oh-my-pi/pi-coding-agent";
import { type Component, Container, Editor, type EditorTheme, Spacer, Text, truncateToWidth } from "@oh-my-pi/pi-tui";
import type { IdentifiedReviewFinding, PreparedReview } from "../schema.ts";
import { cardIntent, editorIntent, listIntent } from "./keys.ts";
import { type CardEvent, type CardState, CommentStore, clampIndex, listItems, reduceCard } from "./model.ts";
import {
	cardHint,
	listHint,
	renderCommentLabel,
	renderFindingCard,
	renderFindingList,
	renderHeader,
	windowRows,
} from "./render.ts";

export interface NavigatorResult {
	cancelled: boolean;
	comments: Record<string, string>;
}

type NavigatorUI = Pick<ExtensionUIContext, "custom">;

type ListOutcome = { kind: "open"; index: number } | { kind: "submit" } | { kind: "cancel" };

function showFindingList(
	ui: NavigatorUI,
	review: PreparedReview,
	store: CommentStore,
	initial: number,
	signal: AbortSignal | undefined,
): Promise<ListOutcome> {
	const findings = review.findings;
	return ui.custom<ListOutcome>(
		(tui, theme, _keybindings, done) => {
			let selected = clampIndex(initial, findings.length);

			const border = new DynamicBorder((s: string) => theme.fg("border", s));
			const header = new Text("", 1, 0);
			const list = new Text("", 1, 0);
			const hint = new Text(listHint(theme), 1, 0);

			const container = new Container();
			container.addChild(border);
			container.addChild(header);
			container.addChild(new Spacer(1));
			container.addChild(list);
			container.addChild(new Spacer(1));
			container.addChild(hint);
			container.addChild(border);

			function move(delta: number): void {
				selected = clampIndex(selected + delta, findings.length);
				container.invalidate();
			}

			return {
				render: (width: number) => {
					const contentWidth = Math.max(width - 2, 1);
					header.setText(renderHeader(review, store.count, theme));
					list.setText(
						renderFindingList(listItems(findings, store), selected, theme, Math.max(3, tui.terminal.rows - 10))
							.map((line) => truncateToWidth(line, contentWidth))
							.join("\n"),
					);
					hint.setText(truncateToWidth(listHint(theme), contentWidth));
					return container.render(width);
				},
				invalidate: () => container.invalidate(),
				pasteText: () => undefined,
				handleInput: (data: string) => {
					switch (listIntent(data)) {
						case "cancel":
							return done({ kind: "cancel" });
						case "submit":
							return done({ kind: "submit" });
						case "open":
							return done({ kind: "open", index: selected });
						case "prev":
							return move(-1);
						case "next":
							return move(1);
						case "none":
							return;
					}
				},
			};
		},
		{ signal },
	);
}

/** Resolves with the finding the user was last on, so the list reopens where they left it. */
function showFindingCard(
	ui: NavigatorUI,
	findings: IdentifiedReviewFinding[],
	store: CommentStore,
	initial: number,
	signal: AbortSignal | undefined,
): Promise<number> {
	return ui.custom<number>(
		(tui, theme, _keybindings, done) => {
			let state: CardState = { current: clampIndex(initial, findings.length), editing: false };
			let scroll = 0;
			const editorTheme: EditorTheme = {
				borderColor: (s: string) => theme.fg("dim", s),
				selectList: getSelectListTheme(),
				symbols: getSymbolTheme(),
				editorPaddingX: 0,
			};
			const editor = new Editor(editorTheme);
			editor.focused = false;

			const border = new DynamicBorder((s: string) => theme.fg("border", s));
			const card = new Text("", 1, 0);
			const commentLabel = new Text("", 1, 0);
			const hint = new Text("", 1, 0);
			const contentViewport: Component = {
				render: (width: number) => {
					const contentWidth = Math.max(width - 2, 1);
					const maxContentRows = Math.max(4, tui.terminal.rows - 8);
					editor.setMaxHeight(state.editing ? Math.max(3, Math.floor(maxContentRows / 2)) : undefined);
					const rows = [...card.render(contentWidth), "", ...commentLabel.render(contentWidth)];
					if (state.editing) rows.push(...editor.render(contentWidth));
					const viewport = windowRows(rows, state.editing ? Number.MAX_SAFE_INTEGER : scroll, maxContentRows, theme);
					scroll = viewport.start;
					return viewport.lines;
				},
				invalidate: () => {
					card.invalidate();
					commentLabel.invalidate();
					editor.invalidate();
				},
			};

			const container = new Container();
			container.addChild(border);
			container.addChild(contentViewport);
			container.addChild(new Spacer(1));
			container.addChild(hint);
			container.addChild(border);

			function apply(event: CardEvent): void {
				const wasEditing = state.editing;
				state = reduceCard(state, event, store);
				if (event.type === "navigate") scroll = 0;
				// Focus-in is the only moment the buffer is seeded, and it is seeded from the store.
				if (!wasEditing && state.editing) editor.setText(store.get(store.idAt(state.current)));
				editor.focused = state.editing;
				container.invalidate();
			}

			function scrollBy(delta: number): void {
				const pageRows = Math.max(2, tui.terminal.rows - 10);
				scroll = Math.max(0, scroll + Math.sign(delta) * pageRows);
				container.invalidate();
			}

			editor.onSubmit = (value: string) => {
				// The editor has already emptied itself by now; the submitted value is the only copy.
				apply({ type: "submit", value });
			};

			return {
				render: (width: number) => {
					const finding = findings[state.current]!;
					const contentWidth = Math.max(width - 2, 1);
					card.setText(renderFindingCard(finding, state.current, findings.length, theme).join("\n"));
					commentLabel.setText(renderCommentLabel(store.get(store.idAt(state.current)), state.editing, theme));
					hint.setText(truncateToWidth(cardHint(state.editing, theme), contentWidth));
					return container.render(width);
				},
				invalidate: () => container.invalidate(),
				pasteText: (text: string) => {
					if (!state.editing) return;
					editor.pasteText(text);
					container.invalidate();
				},
				handleInput: (data: string) => {
					if (state.editing) {
						// getExpandedText, not getText: a large paste lives in the buffer as a marker that
						// only expands here, and the next focus-in setText() would drop its backing content.
						const buffer = editor.getExpandedText();
						if (editorIntent(data, buffer === "") === "blur") {
							apply({ type: "blurEditor", text: buffer });
							return;
						}
						editor.handleInput(data);
						container.invalidate();
						return;
					}

					switch (cardIntent(data)) {
						case "back":
							return done(state.current);
						case "prev":
							return apply({ type: "navigate", delta: -1 });
						case "next":
							return apply({ type: "navigate", delta: 1 });
						case "edit":
							return apply({ type: "focusEditor" });
						case "scroll_up":
							return scrollBy(-1);
						case "scroll_down":
							return scrollBy(1);
						case "none":
							return;
					}
				},
			};
		},
		{ signal },
	);
}

export async function navigateReviewFindings(
	ui: NavigatorUI,
	review: PreparedReview,
	signal?: AbortSignal,
): Promise<NavigatorResult> {
	if (review.findings.length === 0) return { cancelled: false, comments: {} };

	const store = new CommentStore(review.findings);
	let selected = 0;

	while (true) {
		signal?.throwIfAborted();
		const outcome = await showFindingList(ui, review, store, selected, signal);
		if (outcome.kind === "cancel") return { cancelled: true, comments: {} };
		if (outcome.kind === "submit") return { cancelled: false, comments: store.toComments() };
		selected = await showFindingCard(ui, review.findings, store, outcome.index, signal);
	}
}
