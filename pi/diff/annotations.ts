/** Turns hunk's user notes into the line-anchored feedback the agent receives. */

import type { UserNote } from "./hunk.ts";

function location(note: UserNote): string {
	if (!note.newRange) return note.filePath;
	const [start, end] = note.newRange;
	return start === end ? `${note.filePath}:${start}` : `${note.filePath}:${start}-${end}`;
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
