import {
	getSelectListTheme,
	type KeybindingsManager,
	type Theme,
	type ThemeColor,
} from "@mariozechner/pi-coding-agent";
import { type Component, Editor, type EditorTheme, type Focusable, matchesKey, type TUI } from "@mariozechner/pi-tui";
import type { DialogState, Question, QuestionAnswer, SelectAnswer, TextAnswer } from "./types.js";

/** Focus area within an option question. */
type FocusArea = "options" | "editor";

export class EscalateDialog implements Component, Focusable {
	private state: DialogState;
	private tui: TUI;
	private theme: Theme;
	private done: (result: QuestionAnswer[] | null) => void;
	private editor: Editor;
	private focusArea: FocusArea = "options";
	focused = false;

	constructor(
		questions: Question[],
		tui: TUI,
		theme: Theme,
		_keybindings: KeybindingsManager,
		done: (result: QuestionAnswer[] | null) => void,
	) {
		this.state = {
			questions,
			answers: new Map(),
			currentIndex: 0,
			expanded: false,
			selectedIndex: 0,
			selectedOptions: new Set(),
		};
		this.tui = tui;
		this.theme = theme;
		this.done = done;

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		this.editor = new Editor(tui, editorTheme, { paddingX: 0 });
		this.editor.focused = true;
		this.editor.onSubmit = (value: string) => {
			this.handleEditorSubmit(value);
		};
	}

	invalidate(): void {
		this.tui.requestRender();
	}

	render(width: number): string[] {
		const lines: string[] = [];
		const { questions, currentIndex, expanded, error } = this.state;
		const current = questions[currentIndex];
		const total = questions.length;
		const boxWidth = width - 2;

		if (!current) return lines;

		// Top border
		lines.push(this.theme.fg("dim", `╭${"─".repeat(boxWidth)}╮`));

		// Previous section
		if (total > 1 && currentIndex > 0) {
			const expandIcon = expanded ? "▼" : "▶";
			this.pushBoxLine(lines, `${expandIcon} Previous (${currentIndex} answered) [Tab]`, boxWidth, "dim");
			if (expanded) {
				for (let i = 0; i < currentIndex; i++) {
					const q = questions[i];
					const a = this.state.answers.get(i);
					if (q && a) {
						this.pushBoxLine(lines, `  ${q.question} → ${this.formatAnswer(a)}`, boxWidth, "dim");
					}
				}
			}
			lines.push(this.theme.fg("dim", `├${"─".repeat(boxWidth)}┤`));
		}

		// Counter
		if (total > 1) {
			this.pushBoxLine(lines, `${currentIndex + 1}/${total}`, boxWidth, "dim");
		}

		// Question
		this.pushBoxLine(lines, current.question, boxWidth, "text");

		// Context
		if (current.context) {
			this.pushBoxWrapped(lines, current.context, boxWidth, "dim");
		}

		this.pushBoxLine(lines, "", boxWidth, "dim");

		if (current.options?.length) {
			this.renderOptionQuestion(lines, current, boxWidth);
		} else {
			this.renderTextQuestion(lines, boxWidth);
		}

		// Error
		if (error) {
			this.pushBoxLine(lines, "", boxWidth, "dim");
			this.pushBoxLine(lines, error, boxWidth, "error");
		}

		// Footer
		this.pushBoxLine(lines, "", boxWidth, "dim");
		const footerParts: string[] = [];
		if (currentIndex > 0) footerParts.push("[← Back]");
		if (current.options?.length && this.focusArea === "options") {
			footerParts.push("[Space: Select]");
		}
		const isLast = currentIndex >= questions.length - 1;
		footerParts.push(isLast ? "[Enter: Submit]" : "[Enter: Next]");
		footerParts.push("[Esc: Cancel]");
		this.pushBoxLine(lines, footerParts.join("  "), boxWidth, "dim");

		// Bottom border
		lines.push(this.theme.fg("dim", `╰${"─".repeat(boxWidth)}╯`));

		return lines;
	}

	private renderOptionQuestion(lines: string[], current: Question, boxWidth: number): void {
		const isMulti = current.multiSelect ?? false;
		const options = current.options ?? [];

		for (let i = 0; i < options.length; i++) {
			const option = options[i] ?? "";
			const isSelected = this.state.selectedOptions.has(option);
			const isCursor = this.focusArea === "options" && i === this.state.selectedIndex;

			let prefix: string;
			if (isMulti) {
				prefix = isSelected ? "[x] " : "[ ] ";
			} else {
				prefix = isSelected ? "● " : "○ ";
			}

			if (isCursor) {
				this.pushBoxLine(lines, prefix + option, boxWidth, "accent");
			} else if (isSelected) {
				this.pushBoxLine(lines, prefix + option, boxWidth, "text");
			} else {
				this.pushBoxLine(lines, prefix + option, boxWidth, "dim");
			}
		}

		// "Say more..." editor
		this.pushBoxLine(lines, "", boxWidth, "dim");
		const label = this.focusArea === "editor" ? "Say more..." : "Say more... [↓]";
		this.pushBoxLine(lines, label, boxWidth, "dim");

		const editorLines = this.editor.render(boxWidth - 2);
		for (const line of editorLines) {
			lines.push(this.theme.fg("dim", "│ ") + line + this.theme.fg("dim", " │"));
		}
	}

	private renderTextQuestion(lines: string[], boxWidth: number): void {
		const editorLines = this.editor.render(boxWidth - 2);
		for (const line of editorLines) {
			lines.push(this.theme.fg("dim", "│ ") + line + this.theme.fg("dim", " │"));
		}
	}

	private pushBoxLine(lines: string[], text: string, boxWidth: number, color: ThemeColor): void {
		const { visibleWidth, truncateToWidth } = require("@mariozechner/pi-tui");
		const contentWidth = boxWidth - 2;
		const textWidth = visibleWidth(text) as number;
		const truncated = textWidth > contentWidth ? (truncateToWidth(text, contentWidth) as string) : text;
		const truncatedWidth = visibleWidth(truncated) as number;
		const padding = Math.max(0, contentWidth - truncatedWidth);
		lines.push(
			this.theme.fg("dim", "│ ") + this.theme.fg(color, truncated) + " ".repeat(padding) + this.theme.fg("dim", " │"),
		);
	}

	private pushBoxWrapped(lines: string[], text: string, boxWidth: number, color: ThemeColor): void {
		const { wrapTextWithAnsi, visibleWidth } = require("@mariozechner/pi-tui");
		const contentWidth = boxWidth - 2;
		const wrapped = wrapTextWithAnsi(text, contentWidth) as string[];
		for (const line of wrapped) {
			const lineWidth = visibleWidth(line) as number;
			const padding = Math.max(0, contentWidth - lineWidth);
			lines.push(
				this.theme.fg("dim", "│ ") + this.theme.fg(color, line) + " ".repeat(padding) + this.theme.fg("dim", " │"),
			);
		}
	}

	// ========================================================================
	// Input handling
	// ========================================================================

	handleInput(data: string): void {
		const { questions, currentIndex } = this.state;
		const current = questions[currentIndex];
		if (!current) return;

		if (matchesKey(data, "escape")) {
			this.handleEscape();
			return;
		}

		// Tab — toggle previous section
		if (data === "\t") {
			if (questions.length > 1 && currentIndex > 0) {
				this.state.expanded = !this.state.expanded;
				this.state.error = undefined;
				this.invalidate();
			}
			return;
		}

		if (current.options?.length) {
			this.handleOptionInput(data, current);
		} else {
			this.handleTextInput(data);
		}
	}

	private handleOptionInput(data: string, current: Question): void {
		if (this.focusArea === "editor") {
			this.handleOptionEditorInput(data);
			return;
		}

		const options = current.options ?? [];
		const isMulti = current.multiSelect ?? false;

		// Up arrow
		if (data === "\x1b[A") {
			this.state.selectedIndex = Math.max(0, this.state.selectedIndex - 1);
			this.state.error = undefined;
			this.invalidate();
			return;
		}

		// Down arrow — move within options or jump to editor
		if (data === "\x1b[B") {
			if (this.state.selectedIndex < options.length - 1) {
				this.state.selectedIndex = this.state.selectedIndex + 1;
			} else {
				// Move focus to editor
				this.focusArea = "editor";
				this.editor.focused = true;
			}
			this.state.error = undefined;
			this.invalidate();
			return;
		}

		// Space — toggle selection (multi) or select (single)
		if (data === " ") {
			const option = options[this.state.selectedIndex];
			if (option) {
				if (isMulti) {
					if (this.state.selectedOptions.has(option)) {
						this.state.selectedOptions.delete(option);
					} else {
						this.state.selectedOptions.add(option);
					}
				} else {
					// Single select — replace
					this.state.selectedOptions.clear();
					this.state.selectedOptions.add(option);
				}
				this.state.error = undefined;
				this.invalidate();
			}
			return;
		}

		// Enter — submit
		if (data === "\r" || data === "\n") {
			this.submitOptionAnswer(current);
			return;
		}

		// Back navigation
		if ((data === "\x1b[D" || data === "\x7f") && this.state.currentIndex > 0) {
			this.goBack();
			return;
		}
	}

	private handleOptionEditorInput(data: string): void {
		// Up arrow with empty editor — go back to options
		if (data === "\x1b[A" && this.editor.getText() === "") {
			this.focusArea = "options";
			this.state.selectedIndex = (this.state.questions[this.state.currentIndex]?.options?.length ?? 1) - 1;
			this.invalidate();
			return;
		}

		// Backspace on empty — go back to options
		if ((data === "\x7f" || data === "\b") && this.editor.getText() === "") {
			this.focusArea = "options";
			this.state.selectedIndex = (this.state.questions[this.state.currentIndex]?.options?.length ?? 1) - 1;
			this.invalidate();
			return;
		}

		this.editor.handleInput(data);
		this.invalidate();
	}

	private handleTextInput(data: string): void {
		// Backspace on empty — go back
		if ((data === "\x7f" || data === "\b" || data === "\x1b[D") && this.editor.getText() === "") {
			if (this.state.currentIndex > 0) {
				this.goBack();
			}
			return;
		}

		this.editor.handleInput(data);
		this.invalidate();
	}

	private handleEditorSubmit(value: string): void {
		const current = this.state.questions[this.state.currentIndex];

		if (current?.options?.length) {
			// Option question — editor submit = submit the whole question
			// Pass value explicitly since Editor may clear text after onSubmit
			this.submitOptionAnswer(current, value);
		} else {
			// Text question — must have content
			const trimmed = value.trim();
			if (!trimmed) {
				this.state.error = "Answer cannot be empty";
				this.invalidate();
				return;
			}
			this.submitTextAnswer(trimmed);
		}
	}

	// ========================================================================
	// Escape
	// ========================================================================

	private handleEscape(): void {
		// If editor has text, clear it first
		if (this.editor.getText() !== "") {
			this.editor.setText("");
			this.state.error = undefined;
			this.invalidate();
			return;
		}
		// If in editor area, go back to options
		if (this.focusArea === "editor" && this.state.questions[this.state.currentIndex]?.options?.length) {
			this.focusArea = "options";
			this.invalidate();
			return;
		}
		// Dismiss
		this.done(null);
	}

	// ========================================================================
	// Navigation
	// ========================================================================

	private goBack(): void {
		this.state.currentIndex--;
		this.state.error = undefined;
		this.state.selectedIndex = 0;
		this.state.selectedOptions.clear();
		this.focusArea = "options";
		this.editor.setText("");

		// Restore previous state
		const prev = this.state.questions[this.state.currentIndex];
		const prevAnswer = this.state.answers.get(this.state.currentIndex);
		if (prev && prevAnswer) {
			if ("selections" in prevAnswer) {
				for (const s of prevAnswer.selections) {
					this.state.selectedOptions.add(s);
				}
				this.editor.setText(prevAnswer.context ?? "");
			} else if ("answer" in prevAnswer) {
				this.editor.setText(prevAnswer.answer);
			}
		}

		this.invalidate();
	}

	// ========================================================================
	// Submit
	// ========================================================================

	private submitOptionAnswer(current: Question, editorText?: string): void {
		const selections = [...this.state.selectedOptions];
		const context = (editorText ?? this.editor.getText()).trim();

		// Validate: need at least one selection or context
		if (selections.length === 0 && !context) {
			this.state.error = "Select an option or provide context";
			this.invalidate();
			return;
		}

		const answer: SelectAnswer = {
			question: current.question,
			selections,
			...(context ? { context } : {}),
		};
		this.state.answers.set(this.state.currentIndex, answer);
		this.advanceOrComplete();
	}

	private submitTextAnswer(text: string): void {
		const current = this.state.questions[this.state.currentIndex];
		if (!current) return;

		const answer: TextAnswer = {
			question: current.question,
			answer: text,
		};
		this.state.answers.set(this.state.currentIndex, answer);
		this.advanceOrComplete();
	}

	private advanceOrComplete(): void {
		const { questions, currentIndex } = this.state;

		if (currentIndex >= questions.length - 1) {
			const result: QuestionAnswer[] = questions.map((_, i) => this.state.answers.get(i)!);
			this.done(result);
		} else {
			this.state.currentIndex++;
			this.state.selectedIndex = 0;
			this.state.selectedOptions.clear();
			this.state.expanded = false;
			this.state.error = undefined;
			this.focusArea = "options";
			this.editor.setText("");

			// Restore if revisiting
			const next = this.state.questions[this.state.currentIndex];
			const existing = this.state.answers.get(this.state.currentIndex);
			if (next && existing) {
				if ("selections" in existing) {
					for (const s of existing.selections) {
						this.state.selectedOptions.add(s);
					}
					this.editor.setText(existing.context ?? "");
				} else if ("answer" in existing) {
					this.editor.setText(existing.answer);
					this.focusArea = "editor";
				}
			} else if (next && !next.options?.length) {
				this.focusArea = "editor";
			}

			this.invalidate();
		}
	}

	// ========================================================================
	// Helpers
	// ========================================================================

	private formatAnswer(answer: QuestionAnswer): string {
		if ("selections" in answer) {
			const parts = answer.selections.join(", ");
			return answer.context ? `${parts} (${answer.context})` : parts;
		}
		return answer.answer;
	}

	dispose(): void {}
}
