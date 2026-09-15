/**
 * Navigator state: the comment store and the card-view transitions.
 *
 * The store is the single source of truth for comment text, keyed by finding ID so a comment
 * follows its finding no matter where navigation takes the user. The pi-tui Editor is only ever
 * a buffer: it is populated from the store on focus-in, and the store is written exclusively
 * from values carried on events. `Editor.submit()` empties itself *before* invoking `onSubmit`,
 * so any code that reads `getText()` after a submit reads an empty editor and destroys the
 * comment.
 */

import type { IdentifiedReviewFinding } from "../schema.ts";

export class CommentStore {
	private readonly comments = new Map<string, string>();
	private readonly ids: readonly string[];
	readonly total: number;

	constructor(findings: IdentifiedReviewFinding[]) {
		this.ids = findings.map((finding) => finding.id);
		this.total = findings.length;
	}

	/** The finding ID at a list position; card events carry positions, the store carries IDs. */
	idAt(index: number): string {
		return this.ids[index] ?? "";
	}

	get(id: string): string {
		return this.comments.get(id) ?? "";
	}

	has(id: string): boolean {
		return this.comments.has(id);
	}

	/** Trims on write; a blank comment clears the entry rather than storing an empty string. */
	set(id: string, text: string): void {
		const trimmed = text.trim();
		if (trimmed) this.comments.set(id, trimmed);
		else this.comments.delete(id);
	}

	get count(): number {
		return this.comments.size;
	}

	/** Comments keyed by finding ID, in finding order, with uncommented findings absent. */
	toComments(): Record<string, string> {
		const comments: Record<string, string> = {};
		for (const id of this.ids) {
			const comment = this.comments.get(id);
			if (comment !== undefined) comments[id] = comment;
		}
		return comments;
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
			store.set(store.idAt(state.current), event.value);
			return { ...state, editing: false };
		case "blurEditor":
			// Guard, not defensive noise: a submit already left editing mode, so a blur arriving
			// behind it carries the emptied editor and would erase the comment just submitted.
			if (!state.editing) return state;
			store.set(store.idAt(state.current), event.text);
			return { ...state, editing: false };
		case "navigate":
			// Navigation never commits — every editor exit already wrote through to the store.
			if (state.editing) return state;
			return { current: clampIndex(state.current + event.delta, store.total), editing: false };
	}
}

export interface FindingListItem {
	index: number;
	finding: IdentifiedReviewFinding;
	commented: boolean;
}

export function listItems(findings: IdentifiedReviewFinding[], store: CommentStore): FindingListItem[] {
	return findings.map((finding, index) => ({ index, finding, commented: store.has(finding.id) }));
}
