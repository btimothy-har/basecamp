import { describe, expect, test } from "bun:test";
import { type CardState, CommentStore, listItems, reduceCard } from "../navigator/model.ts";
import type { IdentifiedReviewFinding } from "../schema.ts";

function finding(overrides: Partial<IdentifiedReviewFinding> = {}): IdentifiedReviewFinding {
	return {
		id: "finding-1",
		title: "Finding title",
		body: "Finding body",
		priority: 2,
		confidence: 0.8,
		file_path: "src/app.ts",
		line_start: 10,
		line_end: 12,
		...overrides,
	};
}

const findings = [
	finding(),
	finding({ id: "finding-2", title: "Second" }),
	finding({ id: "finding-3", title: "Third" }),
];

function storeWith(entries: Record<string, string>): CommentStore {
	const store = new CommentStore(findings);
	for (const [id, text] of Object.entries(entries)) store.set(id, text);
	return store;
}

function navState(current: number): CardState {
	return { current, editing: false };
}

function editState(current: number): CardState {
	return { current, editing: true };
}

describe("CommentStore", () => {
	test("trims comments and clears the entry when the text is blank", () => {
		const store = new CommentStore(findings);
		store.set("finding-1", "  noted  ");
		expect(store.get("finding-1")).toBe("noted");
		store.set("finding-1", "   ");
		expect(store.has("finding-1")).toBe(false);
		expect(store.get("finding-1")).toBe("");
	});

	test("clears a previously written comment when it is emptied", () => {
		const store = storeWith({ "finding-1": "keep" });
		store.set("finding-1", "");
		expect(store.count).toBe(0);
	});

	test("keys comments by finding ID and omits the uncommented", () => {
		const store = storeWith({ "finding-1": "first note", "finding-3": "third note" });
		expect(store.toComments()).toEqual({ "finding-1": "first note", "finding-3": "third note" });
	});

	test("returns comments in finding order regardless of write order", () => {
		const store = storeWith({ "finding-3": "third note", "finding-1": "first note" });
		expect(Object.keys(store.toComments())).toEqual(["finding-1", "finding-3"]);
	});
});

describe("reduceCard", () => {
	test("keeps a submitted comment when the emptied editor blurs behind the submit", () => {
		const store = new CommentStore(findings);
		const submitted = reduceCard(editState(0), { type: "submit", value: "saved" }, store);
		reduceCard(submitted, { type: "blurEditor", text: "" }, store);
		expect(store.get("finding-1")).toBe("saved");
	});

	test("commits the submitted value under the current finding's ID and leaves editing mode", () => {
		const store = new CommentStore(findings);
		const state = reduceCard(editState(1), { type: "submit", value: "second note" }, store);
		expect(state.editing).toBe(false);
		expect(store.toComments()).toEqual({ "finding-2": "second note" });
	});

	test("commits the editor buffer on blur so escaping out of the editor still saves", () => {
		const store = new CommentStore(findings);
		const state = reduceCard(editState(0), { type: "blurEditor", text: "from blur" }, store);
		expect(state.editing).toBe(false);
		expect(store.get("finding-1")).toBe("from blur");
	});

	test("ignores a submit raised outside editing mode", () => {
		const store = new CommentStore(findings);
		reduceCard(navState(0), { type: "submit", value: "stray" }, store);
		expect(store.count).toBe(0);
	});

	test("enters editing on focus and treats a repeated focus as a no-op", () => {
		const store = new CommentStore(findings);
		const focused = reduceCard(navState(0), { type: "focusEditor" }, store);
		expect(focused.editing).toBe(true);
		expect(reduceCard(focused, { type: "focusEditor" }, store)).toBe(focused);
	});

	test("navigates between findings without touching stored comments", () => {
		const store = storeWith({ "finding-1": "kept" });
		const state = reduceCard(navState(0), { type: "navigate", delta: 1 }, store);
		expect(state.current).toBe(1);
		expect(store.toComments()).toEqual({ "finding-1": "kept" });
	});

	test("clamps navigation at both ends of the finding list", () => {
		const store = new CommentStore(findings);
		expect(reduceCard(navState(0), { type: "navigate", delta: -1 }, store).current).toBe(0);
		expect(reduceCard(navState(2), { type: "navigate", delta: 1 }, store).current).toBe(2);
	});

	test("does not navigate while the editor is focused", () => {
		const store = new CommentStore(findings);
		expect(reduceCard(editState(1), { type: "navigate", delta: 1 }, store)).toEqual(editState(1));
	});
});

describe("listItems", () => {
	test("flags only findings whose ID holds a comment", () => {
		const store = storeWith({ "finding-2": "noted" });
		const items = listItems(findings, store);
		expect(items.map((item) => item.commented)).toEqual([false, true, false]);
		expect(items.map((item) => item.index)).toEqual([0, 1, 2]);
	});
});
