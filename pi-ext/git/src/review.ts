/**
 * PR review overlay — read-only scrollable viewer with inline feedback.
 *
 * Uses pi-tui's Editor component for the body viewer, but only forwards
 * navigation keys — all editing input is blocked. Feedback uses a separate
 * Editor instance.
 *
 * Actions:
 *   Enter       → publish as-is
 *   Tab         → focus feedback editor
 *   Esc         → cancel (viewer) or unfocus (feedback)
 */

import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import { Container, Editor, type EditorTheme, getKeybindings, Spacer, Text } from "@mariozechner/pi-tui";

export type PrReviewResult = { action: "publish" } | { action: "feedback"; text: string } | { action: "cancel" };

const NAV_KEYS = [
	"tui.editor.cursorUp",
	"tui.editor.cursorDown",
	"tui.editor.cursorLeft",
	"tui.editor.cursorRight",
	"tui.editor.cursorWordLeft",
	"tui.editor.cursorWordRight",
	"tui.editor.cursorLineStart",
	"tui.editor.cursorLineEnd",
	"tui.editor.pageUp",
	"tui.editor.pageDown",
] as const;

function isNavKey(data: string): boolean {
	const kb = getKeybindings();
	return NAV_KEYS.some((key) => kb.matches(data, key));
}

export async function showPrReview(
	prNumber: string,
	title: string,
	body: string,
	ctx: ExtensionContext,
): Promise<PrReviewResult> {
	return ctx.ui.custom<PrReviewResult>((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text(`${theme.fg("accent", theme.bold(`PR #${prNumber}`))}  ${title}`, 1, 0);
		const hint = new Text("", 1, 0);
		const feedbackLabel = new Text("", 0, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};

		// Read-only body viewer
		const viewer = new Editor(tui, editorTheme, { paddingX: 0 });
		viewer.setText(body);
		viewer.focused = true;
		viewer.disableSubmit = true;

		// Feedback editor (collapsed by default)
		const feedback = new Editor(tui, editorTheme, { paddingX: 0 });
		feedback.focused = false;

		let feedbackFocused = false;

		feedback.onSubmit = (value: string) => {
			const trimmed = value.trim();
			if (trimmed) {
				done({ action: "feedback", text: trimmed });
			} else {
				// Empty feedback — unfocus back to viewer
				feedbackFocused = false;
				feedback.focused = false;
				viewer.focused = true;
				updateHint();
				container.invalidate();
			}
		};

		function updateHint(): void {
			if (feedbackFocused) {
				hint.setText(theme.fg("dim", "[Enter: Submit feedback]  [Esc: Back]"));
				feedbackLabel.setText(theme.fg("accent", "Feedback"));
			} else {
				hint.setText(theme.fg("dim", "[Enter: Publish]  [Tab: Feedback]  [Esc: Cancel]"));
				feedbackLabel.setText(`${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[Tab]")}`);
			}
		}

		updateHint();

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		// Viewer is rendered manually in render() for height control
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const lines = container.render(width);

				// Insert viewer lines after header spacer
				const viewerLines = viewer.render(width - 2);
				const headerIdx = lines.findIndex((l) => l.includes("PR #"));
				if (headerIdx >= 0) {
					// Insert after header + spacer (headerIdx + 1 is the spacer)
					lines.splice(headerIdx + 2, 0, ...viewerLines);
				}

				// Insert feedback editor when focused
				if (feedbackFocused) {
					const feedbackLines = feedback.render(width - 2);
					const labelIdx = lines.findIndex((l) => l.includes("Feedback"));
					if (labelIdx >= 0) {
						lines.splice(labelIdx + 1, 0, ...feedbackLines);
					}
				}

				return lines;
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				const kb = getKeybindings();

				if (feedbackFocused) {
					if (kb.matches(data, "tui.select.cancel")) {
						if (feedback.getText() !== "") {
							feedback.setText("");
						} else {
							feedbackFocused = false;
							feedback.focused = false;
							viewer.focused = true;
							updateHint();
						}
						container.invalidate();
					} else {
						feedback.handleInput(data);
						container.invalidate();
					}
					return;
				}

				// Viewer mode — navigation only
				if (isNavKey(data)) {
					viewer.handleInput(data);
					container.invalidate();
					return;
				}

				if (kb.matches(data, "tui.input.submit")) {
					done({ action: "publish" });
				} else if (kb.matches(data, "tui.select.cancel")) {
					done({ action: "cancel" });
				} else if (kb.matches(data, "tui.input.tab")) {
					feedbackFocused = true;
					feedback.focused = true;
					viewer.focused = false;
					updateHint();
					container.invalidate();
				}
			},
		};
	});
}
