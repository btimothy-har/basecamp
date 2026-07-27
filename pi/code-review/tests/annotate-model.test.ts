import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { type CardState, CommentStore, listItems, reduceCard } from "#code-review/annotate/model.ts";
import type { Finding } from "#code-review/findings.ts";

function finding(overrides: Partial<Finding> = {}): Finding {
	return {
		dimension: "general",
		severity: "low",
		file: null,
		lineStart: null,
		lineEnd: null,
		title: "Finding title",
		detail: "Finding detail",
		remediation: null,
		...overrides,
	};
}

function navState(current: number): CardState {
	return { current, editing: false };
}

function editState(current: number): CardState {
	return { current, editing: true };
}

describe("CommentStore", () => {
	it("trims comments and clears the entry when the text is blank", () => {
		const store = new CommentStore(3);

		store.set(0, "  intentional  ");
		store.set(1, "   ");

		assert.equal(store.get(0), "intentional");
		assert.equal(store.has(1), false);
		assert.equal(store.get(1), "");
		assert.equal(store.count, 1);
	});

	it("clears a previously written comment when it is emptied", () => {
		const store = new CommentStore(2);
		store.set(0, "first thought");

		store.set(0, "");

		assert.equal(store.has(0), false);
		assert.equal(store.count, 0);
	});

	it("aligns reactions to findings by index and nulls the uncommented", () => {
		const store = new CommentStore(4);
		store.set(0, "intentional");
		store.set(2, "question about this");

		assert.deepEqual(store.toComments(), ["intentional", null, "question about this", null]);
	});
});

describe("reduceCard", () => {
	it("keeps a submitted comment when the emptied editor blurs behind the submit", () => {
		// pi-tui's Editor.submitValue() resets itself to a single empty line *before* invoking
		// onSubmit, so any blur arriving after a submit carries "". Committing it would erase the
		// comment the user just saved — the bug this reducer exists to make impossible.
		const store = new CommentStore(2);

		const afterSubmit = reduceCard(editState(0), { type: "submit", value: "looks intentional" }, store);
		const afterBlur = reduceCard(afterSubmit, { type: "blurEditor", text: "" }, store);

		assert.equal(store.get(0), "looks intentional");
		assert.equal(afterSubmit.editing, false);
		assert.deepEqual(afterBlur, afterSubmit);
	});

	it("commits the submitted value and leaves editing mode", () => {
		const store = new CommentStore(2);

		const next = reduceCard(editState(1), { type: "submit", value: "  needs a test  " }, store);

		assert.deepEqual(next, navState(1));
		assert.equal(store.get(1), "needs a test");
	});

	it("commits the editor buffer on blur so escaping out of the editor still saves", () => {
		const store = new CommentStore(2);

		const next = reduceCard(editState(0), { type: "blurEditor", text: "half-written note" }, store);

		assert.deepEqual(next, navState(0));
		assert.equal(store.get(0), "half-written note");
	});

	it("ignores a submit raised outside editing mode", () => {
		const store = new CommentStore(2);

		const next = reduceCard(navState(0), { type: "submit", value: "stray" }, store);

		assert.deepEqual(next, navState(0));
		assert.equal(store.count, 0);
	});

	it("enters editing on focus and treats a repeated focus as a no-op", () => {
		const store = new CommentStore(2);

		const focused = reduceCard(navState(0), { type: "focusEditor" }, store);
		const refocused = reduceCard(focused, { type: "focusEditor" }, store);

		assert.deepEqual(focused, editState(0));
		assert.equal(refocused, focused);
	});

	it("navigates between findings without touching stored comments", () => {
		const store = new CommentStore(3);
		store.set(0, "kept");

		const next = reduceCard(navState(0), { type: "navigate", delta: 1 }, store);

		assert.deepEqual(next, navState(1));
		assert.equal(store.get(0), "kept");
	});

	it("clamps navigation at both ends of the finding list", () => {
		const store = new CommentStore(3);

		assert.deepEqual(reduceCard(navState(0), { type: "navigate", delta: -1 }, store), navState(0));
		assert.deepEqual(reduceCard(navState(2), { type: "navigate", delta: 1 }, store), navState(2));
	});

	it("does not navigate while the editor is focused", () => {
		const store = new CommentStore(3);

		const next = reduceCard(editState(1), { type: "navigate", delta: 1 }, store);

		assert.deepEqual(next, editState(1));
	});
});

describe("listItems", () => {
	it("flags which findings already carry a comment", () => {
		const store = new CommentStore(3);
		store.set(1, "disagree");
		const findings = [finding({ title: "first" }), finding({ title: "second" }), finding({ title: "third" })];

		const items = listItems(findings, store);

		assert.deepEqual(
			items.map((item) => [item.index, item.finding.title, item.commented]),
			[
				[0, "first", false],
				[1, "second", true],
				[2, "third", false],
			],
		);
	});
});
