/**
 * The annotation pane: a finding list that drills into a card carrying an optional user comment.
 *
 * Both views read comment text from the CommentStore and write it back only through card events —
 * the Editor is a buffer, never an authority. See model.ts for why that ownership matters.
 */

import type { ExtensionUIContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@earendil-works/pi-coding-agent";
import { type Component, Container, Editor, type EditorTheme, Spacer, Text } from "@earendil-works/pi-tui";
import type { Finding } from "#code-review/findings.ts";
import { cardIntent, editorIntent, listIntent } from "./keys.ts";
import { type CardEvent, type CardState, CommentStore, clampIndex, listItems, reduceCard } from "./model.ts";
import {
	cardHint,
	listHint,
	renderCommentLabel,
	renderFindingCard,
	renderFindingList,
	renderHeader,
} from "./render.ts";

export interface AnnotateResult {
	cancelled: boolean;
	reactions: (string | null)[];
}

type AnnotateUI = Pick<ExtensionUIContext, "custom">;

type ListOutcome = { kind: "open"; index: number } | { kind: "submit" } | { kind: "cancel" };

const EDITOR_INSET = 2;

function showFindingList(
	ui: AnnotateUI,
	findings: Finding[],
	store: CommentStore,
	initial: number,
): Promise<ListOutcome> {
	return ui.custom<ListOutcome>((_tui, theme, _keybindings, done) => {
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
				header.setText(renderHeader(findings.length, store.count, theme));
				list.setText(renderFindingList(listItems(findings, store), selected, theme).join("\n"));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
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
	});
}

/** Resolves with the finding the user was last on, so the list reopens where they left it. */
function showFindingCard(ui: AnnotateUI, findings: Finding[], store: CommentStore, initial: number): Promise<number> {
	return ui.custom<number>((tui, theme, _keybindings, done) => {
		let state: CardState = { current: clampIndex(initial, findings.length), editing: false };

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const editor = new Editor(tui, editorTheme, { paddingX: 0 });
		editor.focused = false;

		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const card = new Text("", 1, 0);
		const commentLabel = new Text("", 1, 0);
		const hint = new Text("", 1, 0);
		// A slot child rather than a splice into rendered lines: position must follow the component
		// tree, never a search through text that carries reviewer-authored finding content.
		const editorSlot: Component = {
			render: (width: number) => (state.editing ? editor.render(Math.max(width - EDITOR_INSET, 1)) : []),
			invalidate: () => editor.invalidate(),
		};

		const container = new Container();
		container.addChild(border);
		container.addChild(card);
		container.addChild(new Spacer(1));
		container.addChild(commentLabel);
		container.addChild(editorSlot);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		function apply(event: CardEvent): void {
			const wasEditing = state.editing;
			state = reduceCard(state, event, store);
			// Focus-in is the only moment the buffer is seeded, and it is seeded from the store.
			if (!wasEditing && state.editing) editor.setText(store.get(state.current));
			editor.focused = state.editing;
			container.invalidate();
		}

		editor.onSubmit = (value: string) => {
			// The editor has already emptied itself by now; the submitted value is the only copy.
			apply({ type: "submit", value });
		};

		return {
			render: (width: number) => {
				const finding = findings[state.current]!;
				card.setText(renderFindingCard(finding, state.current, findings.length, theme).join("\n"));
				commentLabel.setText(renderCommentLabel(store.get(state.current), state.editing, theme));
				hint.setText(cardHint(state.editing, theme));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
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
					case "none":
						return;
				}
			},
		};
	});
}

export async function annotateFindings(ui: AnnotateUI, findings: Finding[]): Promise<AnnotateResult> {
	if (findings.length === 0) return { cancelled: false, reactions: [] };

	const store = new CommentStore(findings.length);
	let selected = 0;

	while (true) {
		const outcome = await showFindingList(ui, findings, store, selected);
		if (outcome.kind === "cancel") return { cancelled: true, reactions: [] };
		if (outcome.kind === "submit") return { cancelled: false, reactions: store.toComments() };
		selected = await showFindingCard(ui, findings, store, outcome.index);
	}
}
