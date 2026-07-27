/** Turns hunk's user notes into the line-anchored feedback the agent receives. */

import type { UserNote } from "./hunk.ts";

function span(range: [number, number]): string {
	const [start, end] = range;
	return start === end ? `${start}` : `${start}-${end}`;
}

/**
 * Reviewing a deletion is ordinary, and such a note carries only an old-side
 * range — reporting it as a bare filename would strand the agent's most
 * specific feedback on the file rather than the lines it is about.
 */
function location(note: UserNote): string {
	if (note.newRange) return `${note.filePath}:${span(note.newRange)}`;
	if (note.oldRange) return `${note.filePath}:${span(note.oldRange)} (removed lines)`;
	return note.filePath;
}

export function formatAnnotations(notes: UserNote[]): string {
	const entries = notes.map((note) => `- ${location(note)}\n  ${note.body.trim().split("\n").join("\n  ")}`);
	return [
		`I reviewed the diff and left ${notes.length} annotation${notes.length === 1 ? "" : "s"}:`,
		"",
		...entries,
		"",
		"Address these together with me — discuss before editing.",
	].join("\n");
}
