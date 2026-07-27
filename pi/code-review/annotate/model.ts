/**
 * Annotation state: the comment store and the card-view transitions.
 *
 * The store is the single source of truth for comment text. The pi-tui Editor is only ever a
 * buffer: it is populated from the store on focus-in, and the store is written exclusively from
 * values carried on events. `Editor.submitValue()` empties itself *before* invoking `onSubmit`, so
 * any code that reads `getText()` after a submit reads an empty editor and destroys the comment.
 *
 * "Comment" is the word everywhere inside the domain; "reaction" belongs to the packet schema, and
 * `toComments()`'s caller converts at that boundary.
 */

import type { Finding } from "#code-review/findings.ts";

export class CommentStore {
	private readonly comments = new Map<number, string>();
	readonly total: number;

	constructor(total: number) {
		this.total = total;
	}

	get(index: number): string {
		return this.comments.get(index) ?? "";
	}

	has(index: number): boolean {
		return this.comments.has(index);
	}

	/** Trims on write; a blank comment clears the entry rather than storing an empty string. */
	set(index: number, text: string): void {
		const trimmed = text.trim();
		if (trimmed) this.comments.set(index, trimmed);
		else this.comments.delete(index);
	}

	get count(): number {
		return this.comments.size;
	}

	/** One slot per finding, index-aligned, with `null` where the user left no comment. */
	toComments(): (string | null)[] {
		return Array.from({ length: this.total }, (_unused, index) => this.comments.get(index) ?? null);
	}
}

export interface CardState {
	current: number;
	editing: boolean;
}

export type CardEvent =
	| { type: "focusEditor" }
	| { type: "submit"; value: string }
	| { type: "blurEditor"; text: string }
	| { type: "navigate"; delta: number };

export function clampIndex(index: number, total: number): number {
	if (index < 0) return 0;
	if (index > total - 1) return Math.max(total - 1, 0);
	return index;
}

export function reduceCard(state: CardState, event: CardEvent, store: CommentStore): CardState {
	switch (event.type) {
		case "focusEditor":
			return state.editing ? state : { ...state, editing: true };
		case "submit":
			if (!state.editing) return state;
			store.set(state.current, event.value);
			return { ...state, editing: false };
		case "blurEditor":
			// Guard, not defensive noise: a submit already left editing mode, so a blur arriving
			// behind it carries the emptied editor and would erase the comment just submitted.
			if (!state.editing) return state;
			store.set(state.current, event.text);
			return { ...state, editing: false };
		case "navigate":
			// Navigation never commits — every editor exit already wrote through to the store.
			if (state.editing) return state;
			return { current: clampIndex(state.current + event.delta, store.total), editing: false };
	}
}

export interface FindingListItem {
	index: number;
	finding: Finding;
	commented: boolean;
}

export function listItems(findings: Finding[], store: CommentStore): FindingListItem[] {
	return findings.map((finding, index) => ({ index, finding, commented: store.has(index) }));
}
