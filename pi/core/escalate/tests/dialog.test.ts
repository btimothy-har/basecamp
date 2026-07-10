import assert from "node:assert/strict";
import { test } from "node:test";
import type { KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import type { TUI } from "@earendil-works/pi-tui";
import { EscalateDialog } from "../dialog/index.ts";
import type { DialogState, Question, QuestionAnswer } from "../types.ts";

type FocusArea = "options" | "editor";

type TestDialog = {
	handleInput(data: string): void;
	state: DialogState;
	focusArea: FocusArea;
};

function createDialog(questions: Question[] = [{ question: "Pick?", options: ["one", "two", "three"] }]) {
	const tui = { requestRender() {} } as unknown as TUI;
	const theme = { fg: (_c: string, s: string) => s, bold: (s: string) => s } as unknown as Theme;
	const keybindings = {} as unknown as KeybindingsManager;
	let done: QuestionAnswer[] | null | undefined;
	const dialog = new EscalateDialog(questions, tui, theme, keybindings, (result) => {
		done = result;
	}) as unknown as TestDialog;

	return { dialog, getDone: () => done };
}

test("option Down via CSI moves selectedIndex from 0 to 1", () => {
	const { dialog } = createDialog();

	dialog.handleInput("\x1b[B");

	assert.equal(dialog.state.selectedIndex, 1);
});

test("option Down via SS3 moves selectedIndex from 0 to 1", () => {
	const { dialog } = createDialog();

	dialog.handleInput("\x1bOB");

	assert.equal(dialog.state.selectedIndex, 1);
});

test("option Up via SS3 moves selectedIndex from 1 to 0", () => {
	const { dialog } = createDialog();
	dialog.state.selectedIndex = 1;

	dialog.handleInput("\x1bOA");

	assert.equal(dialog.state.selectedIndex, 0);
});

test("option Down past the last option moves focus to the editor", () => {
	const { dialog } = createDialog();
	dialog.state.selectedIndex = dialog.state.questions[0]!.options!.length - 1;

	dialog.handleInput("\x1b[B");

	assert.equal(dialog.focusArea, "editor");
});

test("SS3 Up from an empty option editor returns focus to options", () => {
	const { dialog } = createDialog();
	dialog.focusArea = "editor";

	dialog.handleInput("\x1bOA");

	assert.equal(dialog.focusArea, "options");
});

test("SS3 Left on Q2 of a multi-question dialog goes back to Q1", () => {
	const { dialog, getDone } = createDialog([
		{ question: "Pick?", options: ["one", "two", "three"] },
		{ question: "Pick again?", options: ["alpha", "beta"] },
	]);
	dialog.handleInput(" ");
	dialog.handleInput("\r");
	assert.equal(dialog.state.currentIndex, 1);

	dialog.handleInput("\x1bOD");

	assert.equal(dialog.state.currentIndex, 0);
	assert.equal(dialog.focusArea, "options");
	assert.deepEqual([...dialog.state.selectedOptions], ["one"]);
	assert.equal(getDone(), undefined);
});
