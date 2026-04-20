/** A single question to ask the user. */
export interface Question {
	question: string;
	context?: string;
	options?: string[];
	/** Allow multiple selections. Defaults to false (single select). Only applies when options are provided. */
	multiSelect?: boolean;
}

/** Answer for a text question (no options). */
export interface TextAnswer {
	question: string;
	answer: string;
}

/** Answer for an option question (single or multi select). */
export interface SelectAnswer {
	question: string;
	selections: string[];
	context?: string;
}

/** A question with its answer. */
export type QuestionAnswer = TextAnswer | SelectAnswer;

/** Internal state for the escalate dialog. */
export interface DialogState {
	questions: Question[];
	answers: Map<number, QuestionAnswer>;
	currentIndex: number;
	expanded: boolean;
	selectedIndex: number;
	/** Toggled selections for multi-select (or single selected option). */
	selectedOptions: Set<string>;
	error?: string;
}
