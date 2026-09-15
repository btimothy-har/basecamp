import { describe, expect, test } from "bun:test";
import { cardIntent, editorIntent, listIntent } from "../navigator/keys.ts";

const ESC = "\x1b";
const CTRL_C = "\x03";
const ENTER = "\r";
const TAB = "\t";
const UP = "\x1b[A";
const DOWN = "\x1b[B";
const RIGHT = "\x1b[C";
const LEFT = "\x1b[D";
const PAGE_UP = "\x1b[5~";
const PAGE_DOWN = "\x1b[6~";
const BACKSPACE = "\x7f";

describe("listIntent", () => {
	test("maps navigation, open, submit, and cancel keys", () => {
		expect(listIntent(UP)).toBe("prev");
		expect(listIntent(DOWN)).toBe("next");
		expect(listIntent(" ")).toBe("open");
		expect(listIntent(ENTER)).toBe("open");
		expect(listIntent("s")).toBe("submit");
		expect(listIntent("S")).toBe("submit");
		expect(listIntent(ESC)).toBe("cancel");
	});

	test("keeps ctrl+c as a discard, matching the pane it replaces", () => {
		expect(listIntent(CTRL_C)).toBe("cancel");
	});

	test("ignores unmapped keys", () => {
		expect(listIntent("z")).toBe("none");
	});
});

describe("cardIntent", () => {
	test("opens the comment box on the down arrow and on tab", () => {
		expect(cardIntent(DOWN)).toBe("edit");
		expect(cardIntent(TAB)).toBe("edit");
	});

	test("does not open the comment box on enter", () => {
		expect(cardIntent(ENTER)).toBe("none");
	});

	test("moves between findings and returns to the list", () => {
		expect(cardIntent(LEFT)).toBe("prev");
		expect(cardIntent(RIGHT)).toBe("next");
		expect(cardIntent(ESC)).toBe("back");
	});

	test("scrolls long cards with page keys", () => {
		expect(cardIntent(PAGE_UP)).toBe("scroll_up");
		expect(cardIntent(PAGE_DOWN)).toBe("scroll_down");
	});
});

describe("editorIntent", () => {
	test("blurs on escape so leaving the comment box commits the buffer", () => {
		expect(editorIntent(ESC, false)).toBe("blur");
	});

	test("blurs on up or backspace only when the buffer is empty", () => {
		expect(editorIntent(UP, true)).toBe("blur");
		expect(editorIntent(BACKSPACE, true)).toBe("blur");
		expect(editorIntent(UP, false)).toBe("passthrough");
		expect(editorIntent(BACKSPACE, false)).toBe("passthrough");
	});

	test("passes typing and enter through to the editor", () => {
		expect(editorIntent("a", false)).toBe("passthrough");
		expect(editorIntent(ENTER, false)).toBe("passthrough");
	});
});
