import type { AutocompleteItem, AutocompleteProvider } from "@oh-my-pi/pi-tui";

const REVIEW_AUTOCOMPLETE = Symbol.for("basecamp.review.autocomplete");
const COMMAND_NAME = /^\s*\/[^/\s]*$/;

type Suggestions = { items: AutocompleteItem[]; prefix: string };

function filterReviewItems(result: Suggestions | null, description: string): Suggestions | null {
	if (!result) return null;

	let keptBasecamp = false;
	let filtered: AutocompleteItem[] | undefined;
	for (const [index, item] of result.items.entries()) {
		if (item.value !== "review") {
			filtered?.push(item);
			continue;
		}

		if (!keptBasecamp && item.description === description) {
			keptBasecamp = true;
			filtered?.push(item);
			continue;
		}

		filtered ??= result.items.slice(0, index);
	}

	if (!filtered) return result;
	return filtered.length === 0 ? null : { items: filtered, prefix: result.prefix };
}

function isCommandNameCompletion(lines: string[], cursorLine: number, cursorCol: number): boolean {
	for (let index = 0; index < cursorLine; index++) {
		if (lines[index]?.trim()) return false;
	}
	return COMMAND_NAME.test((lines[cursorLine] ?? "").slice(0, cursorCol));
}

export default function createReviewAutocompleteProvider(
	current: AutocompleteProvider,
	description: string,
): AutocompleteProvider {
	if (Reflect.get(current, REVIEW_AUTOCOMPLETE) === true) return current;

	const wrapper: AutocompleteProvider = {
		async getSuggestions(lines, cursorLine, cursorCol, signal) {
			const result = await current.getSuggestions.call(current, lines, cursorLine, cursorCol, signal);
			return isCommandNameCompletion(lines, cursorLine, cursorCol) ? filterReviewItems(result, description) : result;
		},
		applyCompletion: current.applyCompletion.bind(current),
	};

	if (current.getInlineHint) wrapper.getInlineHint = current.getInlineHint.bind(current);
	if (current.trySyncSlashCompletion) {
		const trySyncSlashCompletion = current.trySyncSlashCompletion.bind(current);
		wrapper.trySyncSlashCompletion = (textBeforeCursor) => {
			const result = trySyncSlashCompletion(textBeforeCursor);
			return COMMAND_NAME.test(textBeforeCursor) ? filterReviewItems(result, description) : result;
		};
	}
	if (current.trySyncInlineReplace) wrapper.trySyncInlineReplace = current.trySyncInlineReplace.bind(current);
	if (current.getForceFileSuggestions) {
		wrapper.getForceFileSuggestions = current.getForceFileSuggestions.bind(current);
	}
	if (current.shouldTriggerFileCompletion) {
		wrapper.shouldTriggerFileCompletion = current.shouldTriggerFileCompletion.bind(current);
	}

	Object.defineProperty(wrapper, REVIEW_AUTOCOMPLETE, { value: true });
	return wrapper;
}
