/**
 * Issue review overlay — read-only scrollable viewer with inline feedback.
 */

import type { ExtensionContext } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import { Container, Editor, type EditorTheme, getKeybindings, Spacer, Text } from "@mariozechner/pi-tui";

export interface IssueReviewInput {
	repo: string;
	visibility: string;
	draftPath: string;
	title: string;
	body: string;
	topic?: string;
}

export type IssueReviewResult = { action: "publish" } | { action: "feedback"; text: string } | { action: "cancel" };

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

export async function showIssueReview(
	input: IssueReviewInput,
	ctx: ExtensionContext,
): Promise<IssueReviewResult> {
	return ctx.ui.custom<IssueReviewResult>((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text(theme.fg("accent", theme.bold("GitHub Issue Review")), 1, 0);
		const repoLine = new Text(
			`${theme.fg("dim", "Repo")}  ${theme.fg("accent", input.repo)}  ${theme.fg("dim", "Visibility")}  ${input.visibility}`,
			1,
			0,
		);
		const draftLine = new Text(`${theme.fg("dim", "Draft/source")}  ${input.draftPath}`, 1, 0);
		const topicLine = input.topic ? new Text(`${theme.fg("dim", "Topic")}  ${input.topic}`, 1, 0) : null;
		const titleLine = new Text(`${theme.fg("dim", "Title")}  ${theme.fg("accent", theme.bold(input.title))}`, 1, 0);
		const bodyLabel = new Text(theme.fg("dim", "Body"), 0, 0);
		const hint = new Text("", 1, 0);
		const feedbackLabel = new Text("", 0, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};

		const viewer = new Editor(tui, editorTheme, { paddingX: 0 });
		viewer.setText(input.body);
		const viewerState = viewer as unknown as { state: { cursorLine: number; cursorCol: number }; scrollOffset: number };
		viewerState.state.cursorLine = 0;
		viewerState.state.cursorCol = 0;
		viewerState.scrollOffset = 0;
		viewer.focused = true;
		viewer.disableSubmit = true;

		const feedback = new Editor(tui, editorTheme, { paddingX: 0 });
		feedback.focused = false;

		let feedbackFocused = false;

		feedback.onSubmit = (value: string) => {
			const trimmed = value.trim();
			if (trimmed) {
				done({ action: "feedback", text: trimmed });
			} else {
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
		container.addChild(repoLine);
		container.addChild(draftLine);
		if (topicLine) container.addChild(topicLine);
		container.addChild(new Spacer(1));
		container.addChild(titleLine);
		container.addChild(new Spacer(1));
		container.addChild(bodyLabel);
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const lines = container.render(width);
				const bodyIdx = lines.findIndex((l) => l.includes("Body"));
				let feedbackIdx = lines.findIndex((l) => l.includes("Feedback"));

				if (bodyIdx >= 0) {
					const viewerLines = viewer.render(width - 2);
					lines.splice(bodyIdx + 1, 0, ...viewerLines);
					if (feedbackIdx > bodyIdx) feedbackIdx += viewerLines.length;
				}

				if (feedbackFocused && feedbackIdx >= 0) {
					const feedbackLines = feedback.render(width - 2);
					lines.splice(feedbackIdx + 1, 0, ...feedbackLines);
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
