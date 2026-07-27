import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { cardIntent, editorIntent, listIntent } from "#code-review/annotate/keys.ts";

const ESC = "\x1b";
const CTRL_C = "\x03";
const ENTER = "\r";
const TAB = "\t";
const UP = "\x1b[A";
const DOWN = "\x1b[B";
const RIGHT = "\x1b[C";
const LEFT = "\x1b[D";
const BACKSPACE = "\x7f";

describe("listIntent", () => {
	it("maps navigation, open, submit, and cancel keys", () => {
		assert.equal(listIntent(UP), "prev");
		assert.equal(listIntent(DOWN), "next");
		assert.equal(listIntent(" "), "open");
		assert.equal(listIntent(ENTER), "open");
		assert.equal(listIntent("s"), "submit");
		assert.equal(listIntent(ESC), "cancel");
	});

	it("keeps ctrl+c as a discard, matching the pane it replaces", () => {
		assert.equal(listIntent(CTRL_C), "cancel");
	});

	it("ignores unmapped keys", () => {
		assert.equal(listIntent("z"), "none");
	});
});

describe("cardIntent", () => {
	it("opens the comment box on the down arrow and on tab", () => {
		assert.equal(cardIntent(DOWN), "edit");
		assert.equal(cardIntent(TAB), "edit");
	});

	it("does not open the comment box on enter", () => {
		assert.equal(cardIntent(ENTER), "none");
	});

	it("moves between findings and returns to the list", () => {
		assert.equal(cardIntent(LEFT), "prev");
		assert.equal(cardIntent(RIGHT), "next");
		assert.equal(cardIntent(ESC), "back");
	});
});

describe("editorIntent", () => {
	it("blurs on escape so leaving the comment box commits the buffer", () => {
		assert.equal(editorIntent(ESC, false), "blur");
	});

	it("blurs on up or backspace only when the buffer is empty", () => {
		assert.equal(editorIntent(UP, true), "blur");
		assert.equal(editorIntent(BACKSPACE, true), "blur");
		assert.equal(editorIntent(UP, false), "passthrough");
		assert.equal(editorIntent(BACKSPACE, false), "passthrough");
	});

	it("passes typing and enter through to the editor", () => {
		assert.equal(editorIntent("a", false), "passthrough");
		assert.equal(editorIntent(ENTER, false), "passthrough");
	});
});
