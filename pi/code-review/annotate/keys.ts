/** Keystroke-to-intent mapping for the annotation views. Pure, so the key contract is testable. */

import { getKeybindings, matchesKey } from "@earendil-works/pi-tui";

export type ListIntent = "prev" | "next" | "open" | "submit" | "cancel" | "none";
export type CardIntent = "prev" | "next" | "edit" | "back" | "none";
export type EditorIntent = "blur" | "passthrough";

function isCancel(data: string): boolean {
	return getKeybindings().matches(data, "tui.select.cancel");
}

export function listIntent(data: string): ListIntent {
	if (isCancel(data)) return "cancel";
	if (matchesKey(data, "up")) return "prev";
	if (matchesKey(data, "down")) return "next";
	if (matchesKey(data, "space") || matchesKey(data, "enter")) return "open";
	if (matchesKey(data, "s") || matchesKey(data, "shift+s")) return "submit";
	return "none";
}

export function cardIntent(data: string): CardIntent {
	if (isCancel(data)) return "back";
	if (matchesKey(data, "left")) return "prev";
	if (matchesKey(data, "right")) return "next";
	// Enter deliberately does not reach the comment box; ↓ and Tab are the only ways in.
	if (matchesKey(data, "down") || matchesKey(data, "tab")) return "edit";
	return "none";
}

/** Blur commits the buffer, so leaving the comment box always saves whatever is in it. */
export function editorIntent(data: string, bufferEmpty: boolean): EditorIntent {
	if (isCancel(data)) return "blur";
	if (bufferEmpty && (matchesKey(data, "up") || matchesKey(data, "backspace"))) return "blur";
	return "passthrough";
}
