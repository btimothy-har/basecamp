/** Escalate dialog rendering — pure view functions over the dialog state. */

import type { Theme, ThemeColor } from "@earendil-works/pi-coding-agent";
import type { Editor } from "@earendil-works/pi-tui";
import type { DialogState, Question, QuestionAnswer } from "../types.ts";

/** Focus area within an option question. */
export type FocusArea = "options" | "editor";

/** The slice of EscalateDialog the renderer reads. */
export interface DialogView {
	state: DialogState;
	theme: Theme;
	editor: Editor;
	focusArea: FocusArea;
}

export function renderDialog(view: DialogView, width: number): string[] {
	const lines: string[] = [];
	const { questions, currentIndex, expanded, error } = view.state;
	const current = questions[currentIndex];
	const total = questions.length;
	const boxWidth = width - 2;

	if (!current) return lines;

	// Top border
	lines.push(view.theme.fg("dim", `╭${"─".repeat(boxWidth)}╮`));

	// Previous section
	if (total > 1 && currentIndex > 0) {
		const expandIcon = expanded ? "▼" : "▶";
		pushBoxLine(view.theme, lines, `${expandIcon} Previous (${currentIndex} answered) [Tab]`, boxWidth, "dim");
		if (expanded) {
			for (let i = 0; i < currentIndex; i++) {
				const q = questions[i];
				const a = view.state.answers.get(i);
				if (q && a) {
					pushBoxLine(view.theme, lines, `  ${q.question} → ${formatAnswer(a)}`, boxWidth, "dim");
				}
			}
		}
		lines.push(view.theme.fg("dim", `├${"─".repeat(boxWidth)}┤`));
	}

	// Counter
	if (total > 1) {
		pushBoxLine(view.theme, lines, `${currentIndex + 1}/${total}`, boxWidth, "dim");
	}

	// Question
	pushBoxLine(view.theme, lines, current.question, boxWidth, "text");

	// Context
	if (current.context) {
		pushBoxWrapped(view.theme, lines, current.context, boxWidth, "dim");
	}

	pushBoxLine(view.theme, lines, "", boxWidth, "dim");

	if (current.options?.length) {
		renderOptionQuestion(view, lines, current, boxWidth);
	} else {
		renderTextQuestion(view, lines, boxWidth);
	}

	// Error
	if (error) {
		pushBoxLine(view.theme, lines, "", boxWidth, "dim");
		pushBoxLine(view.theme, lines, error, boxWidth, "error");
	}

	// Footer
	pushBoxLine(view.theme, lines, "", boxWidth, "dim");
	const footerParts: string[] = [];
	if (currentIndex > 0) footerParts.push("[← Back]");
	if (current.options?.length && view.focusArea === "options") {
		footerParts.push("[Space: Select]");
	}
	const isLast = currentIndex >= questions.length - 1;
	footerParts.push(isLast ? "[Enter: Submit]" : "[Enter: Next]");
	footerParts.push("[Esc: Cancel]");
	pushBoxLine(view.theme, lines, footerParts.join("  "), boxWidth, "dim");

	// Bottom border
	lines.push(view.theme.fg("dim", `╰${"─".repeat(boxWidth)}╯`));

	return lines;
}

function renderOptionQuestion(view: DialogView, lines: string[], current: Question, boxWidth: number): void {
	const isMulti = current.multiSelect ?? false;
	const options = current.options ?? [];

	for (let i = 0; i < options.length; i++) {
		const option = options[i] ?? "";
		const isSelected = view.state.selectedOptions.has(option);
		const isCursor = view.focusArea === "options" && i === view.state.selectedIndex;

		let prefix: string;
		if (isMulti) {
			prefix = isSelected ? "[x] " : "[ ] ";
		} else {
			prefix = isSelected ? "● " : "○ ";
		}

		if (isCursor) {
			pushBoxLine(view.theme, lines, prefix + option, boxWidth, "accent");
		} else if (isSelected) {
			pushBoxLine(view.theme, lines, prefix + option, boxWidth, "text");
		} else {
			pushBoxLine(view.theme, lines, prefix + option, boxWidth, "dim");
		}
	}

	// "Say more..." editor
	pushBoxLine(view.theme, lines, "", boxWidth, "dim");
	const label = view.focusArea === "editor" ? "Say more..." : "Say more... [↓]";
	pushBoxLine(view.theme, lines, label, boxWidth, "dim");

	const editorLines = view.editor.render(boxWidth - 2);
	for (const line of editorLines) {
		lines.push(view.theme.fg("dim", "│ ") + line + view.theme.fg("dim", " │"));
	}
}

function renderTextQuestion(view: DialogView, lines: string[], boxWidth: number): void {
	const editorLines = view.editor.render(boxWidth - 2);
	for (const line of editorLines) {
		lines.push(view.theme.fg("dim", "│ ") + line + view.theme.fg("dim", " │"));
	}
}

function pushBoxLine(theme: Theme, lines: string[], text: string, boxWidth: number, color: ThemeColor): void {
	const { visibleWidth, truncateToWidth } = require("@earendil-works/pi-tui");
	const contentWidth = boxWidth - 2;
	const textWidth = visibleWidth(text) as number;
	const truncated = textWidth > contentWidth ? (truncateToWidth(text, contentWidth) as string) : text;
	const truncatedWidth = visibleWidth(truncated) as number;
	const padding = Math.max(0, contentWidth - truncatedWidth);
	lines.push(theme.fg("dim", "│ ") + theme.fg(color, truncated) + " ".repeat(padding) + theme.fg("dim", " │"));
}

function pushBoxWrapped(theme: Theme, lines: string[], text: string, boxWidth: number, color: ThemeColor): void {
	const { wrapTextWithAnsi, visibleWidth } = require("@earendil-works/pi-tui");
	const contentWidth = boxWidth - 2;
	const wrapped = wrapTextWithAnsi(text, contentWidth) as string[];
	for (const line of wrapped) {
		const lineWidth = visibleWidth(line) as number;
		const padding = Math.max(0, contentWidth - lineWidth);
		lines.push(theme.fg("dim", "│ ") + theme.fg(color, line) + " ".repeat(padding) + theme.fg("dim", " │"));
	}
}

function formatAnswer(answer: QuestionAnswer): string {
	if ("selections" in answer) {
		const parts = answer.selections.join(", ");
		return answer.context ? `${parts} (${answer.context})` : parts;
	}
	return answer.answer;
}
