/**
 * Drives the real annotation-pane components through a fake `ui.custom`, so the pi-tui Editor —
 * including its clear-itself-before-onSubmit and paste-marker behaviour — participates in tests.
 *
 * Not a `.test.ts` file, so the runner's glob leaves it alone.
 */

import assert from "node:assert/strict";
import type { ExtensionUIContext, KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import type { Component, TUI } from "@earendil-works/pi-tui";
import { getKeybindings } from "@earendil-works/pi-tui";

export const ESC = "\x1b";
export const ENTER = "\r";
export const SPACE = " ";
export const DOWN = "\x1b[B";
export const RIGHT = "\x1b[C";
export const LEFT = "\x1b[D";
export const BACKSPACE = "\x7f";

type View = Component & { handleInput?(data: string): void };

/** Receives a keystroke sender and a renderer for the view currently on screen. */
export type Driver = (send: (...keys: string[]) => void, render: () => string) => void;

const tui = { requestRender() {}, terminal: { rows: 40, columns: 80 } } as unknown as TUI;

const theme = {
	fg: (_color: string, text: string) => text,
	bold: (text: string) => text,
} as unknown as Theme;

/** One keystroke per character — the Editor treats a multi-character chunk as pasted text. */
export function type(text: string): string[] {
	return [...text];
}

/** A bracketed paste over pi-tui's 10-line threshold, which the Editor stores behind a marker. */
export function bracketedPaste(lineCount: number): { keys: string; text: string } {
	const text = Array.from({ length: lineCount }, (_unused, index) => `pasted evidence line ${index}`).join("\n");
	return { keys: `\x1b[200~${text}\x1b[201~`, text };
}

export function paneHarness(drivers: Driver[]): Pick<ExtensionUIContext, "custom"> {
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
