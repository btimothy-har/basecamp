/**
 * `/diff` argument parsing — a closed keyword set, never free-form input.
 *
 * `herdr pane run` is unescaped send-keys, so the command's safety story is
 * that nothing the user types can reach a shell. That invariant survives
 * gaining a mode only because the mode is parsed here into an enum: the argv
 * hunk eventually receives is assembled from git output we resolve, never
 * from the raw argument string.
 */

export type DiffMode = { kind: DiffModeKind } | { kind: "invalid"; arg: string };

/** A mode the command can actually run — the closed keyword set, minus rejection. */
export type DiffModeKind = "base" | "last";

export function parseDiffArgs(args: string | undefined | null): DiffMode {
	const trimmed = args?.trim() ?? "";
	if (trimmed === "") return { kind: "base" };
	if (trimmed === "last") return { kind: "last" };
	return { kind: "invalid", arg: trimmed };
}
