/** Escalate dialog answer flow — submission, back navigation, advance/complete. */

import type { Editor } from "@earendil-works/pi-tui";
import type { FocusArea } from "./dialog-render.ts";
import type { DialogState, Question, QuestionAnswer, SelectAnswer, TextAnswer } from "./types.ts";

/** The slice of EscalateDialog the flow functions read and mutate. */
export interface DialogFlowHost {
	state: DialogState;
	editor: Editor;
	focusArea: FocusArea;
	invalidate(): void;
	done: (result: QuestionAnswer[] | null) => void;
}

export function goBack(host: DialogFlowHost): void {
	host.state.currentIndex--;
	host.state.error = undefined;
	host.state.selectedIndex = 0;
	host.state.selectedOptions.clear();
	host.focusArea = "options";
	host.editor.setText("");

	// Restore previous state
	const prev = host.state.questions[host.state.currentIndex];
	const prevAnswer = host.state.answers.get(host.state.currentIndex);
	if (prev && prevAnswer) {
		if ("selections" in prevAnswer) {
			for (const s of prevAnswer.selections) {
				host.state.selectedOptions.add(s);
			}
			host.editor.setText(prevAnswer.context ?? "");
		} else if ("answer" in prevAnswer) {
			host.editor.setText(prevAnswer.answer);
		}
	}

	host.invalidate();
}

export function submitOptionAnswer(host: DialogFlowHost, current: Question, editorText?: string): void {
	const selections = [...host.state.selectedOptions];
	const context = (editorText ?? host.editor.getText()).trim();

	// Validate: need at least one selection or context
	if (selections.length === 0 && !context) {
		host.state.error = "Select an option or provide context";
		host.invalidate();
		return;
	}

	const answer: SelectAnswer = {
		question: current.question,
		selections,
		...(context ? { context } : {}),
	};
	host.state.answers.set(host.state.currentIndex, answer);
	advanceOrComplete(host);
}

export function submitTextAnswer(host: DialogFlowHost, text: string): void {
	const current = host.state.questions[host.state.currentIndex];
	if (!current) return;

	const answer: TextAnswer = {
		question: current.question,
		answer: text,
	};
	host.state.answers.set(host.state.currentIndex, answer);
	advanceOrComplete(host);
}

export function advanceOrComplete(host: DialogFlowHost): void {
	const { questions, currentIndex } = host.state;

	if (currentIndex >= questions.length - 1) {
		const result: QuestionAnswer[] = questions.map((_, i) => host.state.answers.get(i)!);
		host.done(result);
	} else {
		host.state.currentIndex++;
		host.state.selectedIndex = 0;
		host.state.selectedOptions.clear();
		host.state.expanded = false;
		host.state.error = undefined;
		host.focusArea = "options";
		host.editor.setText("");

		// Restore if revisiting
		const next = host.state.questions[host.state.currentIndex];
		const existing = host.state.answers.get(host.state.currentIndex);
		if (next && existing) {
			if ("selections" in existing) {
				for (const s of existing.selections) {
					host.state.selectedOptions.add(s);
				}
				host.editor.setText(existing.context ?? "");
			} else if ("answer" in existing) {
				host.editor.setText(existing.answer);
				host.focusArea = "editor";
			}
		} else if (next && !next.options?.length) {
			host.focusArea = "editor";
		}

		host.invalidate();
	}
}
