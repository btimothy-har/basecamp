/**
 * Drives the real pane components through a fake `ui.custom`, so the pi-tui Editor — including its
 * clear-itself-before-onSubmit behaviour — participates in the test.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionUIContext, KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import type { Component, TUI } from "@earendil-works/pi-tui";
import { getKeybindings } from "@earendil-works/pi-tui";
import { annotateFindings } from "#code-review/annotate/index.ts";
import type { Finding } from "#code-review/findings.ts";

const ESC = "\x1b";
const ENTER = "\r";
const SPACE = " ";
const DOWN = "\x1b[B";
const RIGHT = "\x1b[C";
const LEFT = "\x1b[D";
const BACKSPACE = "\x7f";

type View = Component & { handleInput?(data: string): void };
type Driver = (send: (...keys: string[]) => void, render: () => string) => void;

const tui = { requestRender() {}, terminal: { rows: 40, columns: 80 } } as unknown as TUI;
const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

function harness(drivers: Driver[]): Pick<ExtensionUIContext, "custom"> {
	let opened = 0;
	const custom = <T>(
		factory: (tui: TUI, theme: Theme, keybindings: KeybindingsManager, done: (result: T) => void) => View,
	): Promise<T> =>
		new Promise<T>((resolve) => {
			const driver = drivers[opened++];
			assert.ok(driver, `pane opened ${opened} times but only ${drivers.length} views were scripted`);
			// pi-coding-agent re-exports its own nested pi-tui copy, so the manager needs a cast.
			const view = factory(tui, theme, getKeybindings() as unknown as KeybindingsManager, resolve);
			const render = () => view.render(80).join("\n");
			// Render once so the view is in the same state a real terminal would leave it in.
			render();
			driver((...keys: string[]) => {
				for (const key of keys) view.handleInput?.(key);
			}, render);
		});
	return { custom } as unknown as Pick<ExtensionUIContext, "custom">;
}

/** One keystroke per character — the Editor treats a multi-character chunk as pasted text. */
function type(text: string): string[] {
	return [...text];
}

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

const twoFindings = [finding({ title: "first" }), finding({ title: "second" })];

describe("annotateFindings", () => {
	it("keeps a comment saved with Enter", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("looks intentional"), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: false, reactions: ["looks intentional", null] });
	});

	it("keeps a comment saved with Esc", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("escaped out"), ESC, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: false, reactions: ["escaped out", null] });
	});

	it("redisplays a saved comment when the finding is revisited", async () => {
		let idleView = "";
		let reopenedEditor = "";
		const ui = harness([
			(send) => send(SPACE),
			(send, render) => {
				send(DOWN, ...type("first pass"), ENTER);
				send(RIGHT, DOWN, ...type("other"), ENTER);
				send(LEFT);
				idleView = render();
				send(DOWN);
				reopenedEditor = render();
				send(ESC, ESC);
			},
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.match(idleView, /first pass/);
		assert.match(reopenedEditor, /first pass/);
		assert.deepEqual(result.reactions, ["first pass", "other"]);
	});

	it("marks commented findings in the list", async () => {
		let listView = "";
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("noted"), ENTER, ESC),
			(send, render) => {
				listView = render();
				send("s");
			},
		]);

		await annotateFindings(ui, twoFindings);

		assert.match(listView, /1 commented/);
		assert.match(listView, /first {2}\(no file\):\? {2}📝/);
	});

	it("does not open the comment box on Enter from the card", async () => {
		const ui = harness([
			(send) => send(SPACE),
			// Enter must be inert here; the characters that follow would otherwise become a comment.
			(send) => send(ENTER, ...type("not a comment"), ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result.reactions, [null, null]);
	});

	it("clears a comment when the box is emptied", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("temporary"), ENTER, DOWN, ...Array(9).fill(BACKSPACE), ENTER, ESC),
			(send) => send("s"),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result.reactions, [null, null]);
	});

	it("discards every comment when the list is cancelled", async () => {
		const ui = harness([
			(send) => send(SPACE),
			(send) => send(DOWN, ...type("typed then abandoned"), ENTER, ESC),
			(send) => send(ESC),
		]);

		const result = await annotateFindings(ui, twoFindings);

		assert.deepEqual(result, { cancelled: true, reactions: [] });
	});

	it("returns immediately without opening a view when there are no findings", async () => {
		const result = await annotateFindings(harness([]), []);

		assert.deepEqual(result, { cancelled: false, reactions: [] });
	});
});
