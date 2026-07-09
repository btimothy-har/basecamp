/**
 * Escalate dialog component — input dispatch and focus management.
 * Rendering lives in dialog-render.ts; answer flow in dialog-flow.ts (both
 * operate on this component structurally, so the shared fields are
 * module-visible rather than private).
 */

import { getSelectListTheme, type KeybindingsManager, type Theme } from "@earendil-works/pi-coding-agent";
import { type Component, Editor, type EditorTheme, type Focusable, matchesKey, type TUI } from "@earendil-works/pi-tui";
import { goBack, submitOptionAnswer, submitTextAnswer } from "./dialog-flow.ts";
import { type FocusArea, renderDialog } from "./dialog-render.ts";
import type { DialogState, Question, QuestionAnswer } from "./types.ts";

export class EscalateDialog implements Component, Focusable {
	state: DialogState;
	private tui: TUI;
	theme: Theme;
	done: (result: QuestionAnswer[] | null) => void;
	editor: Editor;
	focusArea: FocusArea = "options";
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
		return renderDialog(this, width);
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
		if (matchesKey(data, "tab")) {
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
		if (matchesKey(data, "up")) {
			this.state.selectedIndex = Math.max(0, this.state.selectedIndex - 1);
			this.state.error = undefined;
			this.invalidate();
			return;
		}

		// Down arrow — move within options or jump to editor
		if (matchesKey(data, "down")) {
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
		if (matchesKey(data, "space")) {
			const option = options[this.state.selectedIndex];
			if (option) {
				if (isMulti) {
					if (this.state.selectedOptions.has(option)) {
						this.state.selectedOptions.delete(option);
					} else {
						this.state.selectedOptions.add(option);
					}
				} else {
					// Single select — toggle current, or switch to new
					if (this.state.selectedOptions.has(option)) {
						this.state.selectedOptions.delete(option);
					} else {
						this.state.selectedOptions.clear();
						this.state.selectedOptions.add(option);
					}
				}
				this.state.error = undefined;
				this.invalidate();
			}
			return;
		}

		// Enter — submit
		if (matchesKey(data, "enter")) {
			submitOptionAnswer(this, current);
			return;
		}

		// Back navigation
		if ((matchesKey(data, "left") || matchesKey(data, "backspace")) && this.state.currentIndex > 0) {
			goBack(this);
			return;
		}
	}

	private handleOptionEditorInput(data: string): void {
		// Up arrow with empty editor — go back to options
		if (matchesKey(data, "up") && this.editor.getText() === "") {
			this.focusArea = "options";
			this.state.selectedIndex = (this.state.questions[this.state.currentIndex]?.options?.length ?? 1) - 1;
			this.invalidate();
			return;
		}

		// Backspace on empty — go back to options
		if (matchesKey(data, "backspace") && this.editor.getText() === "") {
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
		if ((matchesKey(data, "backspace") || matchesKey(data, "left")) && this.editor.getText() === "") {
			if (this.state.currentIndex > 0) {
				goBack(this);
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
			submitOptionAnswer(this, current, value);
		} else {
			// Text question — must have content
			const trimmed = value.trim();
			if (!trimmed) {
				this.state.error = "Answer cannot be empty";
				this.invalidate();
				return;
			}
			submitTextAnswer(this, trimmed);
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

	dispose(): void {}
}
