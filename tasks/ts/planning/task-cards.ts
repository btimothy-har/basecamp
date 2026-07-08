/** Task card viewer — browse tasks with prev/next, collective approve/revise. */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@earendil-works/pi-coding-agent";
import { Container, Editor, type EditorTheme, matchesKey, Spacer, Text } from "@earendil-works/pi-tui";
import { type PlanDraft, reviewMarker } from "./review-model.ts";

export async function showTaskCards(draft: PlanDraft, ctx: ExtensionContext): Promise<void> {
	const tasks = draft.tasks;
	if (tasks.length === 0) return;

	const action = await ctx.ui.custom<"approve" | "revise" | "back">((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const header = new Text("", 1, 0);
		const contentText = new Text("", 0, 0);
		const feedbackLabel = new Text("", 0, 0);
		const hint = new Text("", 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const editor = new Editor(tui, editorTheme, { paddingX: 0 });
		const currentFeedback = draft.tasksReview.feedback ?? "";
		editor.setText(currentFeedback);
		editor.focused = false;

		let currentIdx = 0;
		let editorFocused = false;

		editor.onSubmit = (value: string) => {
			const trimmed = value.trim();
			draft.tasksReview = { approved: draft.tasksReview.approved, feedback: trimmed || null };
			editorFocused = false;
			editor.focused = false;
			updateHint();
			container.invalidate();
		};

		function updateHint(): void {
			if (editorFocused) {
				hint.setText(theme.fg("dim", "[Enter: Save]  [Esc: Clear/Back]"));
				feedbackLabel.setText(theme.fg("accent", "Feedback"));
			} else {
				const parts = ["[←→: Navigate]", "[a: Approve all]", "[r: Revise all]", "[↓: Feedback]", "[Esc: Back]"];
				hint.setText(theme.fg("dim", parts.join("  ")));
				const fb = draft.tasksReview.feedback;
				if (fb) {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}\n${fb}`);
				} else {
					feedbackLabel.setText(`${theme.fg("dim", "Feedback")}  ${theme.fg("dim", "[↓]")}`);
				}
			}
		}

		function renderCard(): string[] {
			const task = tasks[currentIdx]!;
			const lines: string[] = [];
			const idx = theme.fg("dim", `[${currentIdx}]`);
			lines.push(`${idx} ${theme.fg("accent", theme.bold(task.label))}`);
			lines.push("");
			lines.push(`${theme.fg("dim", "Description")}  ${task.description}`);
			lines.push("");
			lines.push(`${theme.fg("dim", "Criteria")}  ${task.criteria}`);
			return lines;
		}

		updateHint();

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(contentText);
		container.addChild(new Spacer(1));
		container.addChild(feedbackLabel);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const marker = reviewMarker(draft.tasksReview, theme);
				header.setText(
					`${marker} ${theme.fg("accent", theme.bold("Tasks"))}  ${theme.fg("dim", `${currentIdx + 1} of ${tasks.length}`)}`,
				);
				contentText.setText(renderCard().join("\n"));
				const lines = container.render(width);
				if (editorFocused) {
					const editorLines = editor.render(width - 2);
					const labelIdx = lines.findIndex((l) => l.includes("Feedback"));
					if (labelIdx >= 0) {
						lines.splice(labelIdx + 1, 0, ...editorLines);
					}
				}
				return lines;
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (editorFocused) {
					if (matchesKey(data, "escape")) {
						if (editor.getText() !== "") {
							editor.setText("");
						} else {
							editorFocused = false;
							editor.focused = false;
							updateHint();
						}
						container.invalidate();
					} else if ((matchesKey(data, "up") || matchesKey(data, "backspace")) && editor.getText() === "") {
						editorFocused = false;
						editor.focused = false;
						updateHint();
						container.invalidate();
					} else {
						editor.handleInput(data);
						container.invalidate();
					}
				} else {
					if (matchesKey(data, "escape")) {
						done("back");
					} else if (matchesKey(data, "a") || matchesKey(data, "shift+a")) {
						done("approve");
					} else if (matchesKey(data, "r") || matchesKey(data, "shift+r")) {
						done("revise");
					} else if (matchesKey(data, "left")) {
						if (currentIdx > 0) {
							currentIdx--;
							container.invalidate();
						}
					} else if (matchesKey(data, "right")) {
						if (currentIdx < tasks.length - 1) {
							currentIdx++;
							container.invalidate();
						}
					} else if (matchesKey(data, "down") || matchesKey(data, "tab")) {
						editorFocused = true;
						editor.focused = true;
						const existingFb = draft.tasksReview.feedback ?? "";
						editor.setText(existingFb);
						updateHint();
						container.invalidate();
					}
				}
			},
		};
	});

	if (action === "approve") {
		draft.tasksReview = { approved: true, feedback: draft.tasksReview.feedback };
	} else if (action === "revise") {
		draft.tasksReview = { approved: false, feedback: draft.tasksReview.feedback };
	}
}
