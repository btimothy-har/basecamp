/**
 * The bash reviewer's fast path: the only code that may let a command run without the LLM gate.
 *
 * A static check here may only ever restrict. It answers "is this trivially safe?", never "is this
 * dangerous?", so an unrecognized construct falls through to the gate instead of passing. That
 * inversion is what removes the need for a shell grammar: a command whose every character is in
 * the safe set cannot contain an expansion, substitution, redirection, separator, glob, or quote,
 * so it is provably one simple command of literal words.
 *
 * The signature is a seam. Replacing this body with an AST recognizer would widen what is
 * recognized — pipelines of read-only commands, quoted literal arguments — without changing the
 * contract. That trade buys a wider fast path for a WASM dependency inside the security control,
 * and is justified only by audit evidence of gated-but-obviously-safe commands.
 */

const SAFE_CHARACTERS = /^[A-Za-z0-9 \t\-_./,:@+]+$/;

const READ_ONLY_EXECUTABLES = new Set(["cat", "file", "head", "ls", "pwd", "stat", "tail", "wc", "which"]);

/**
 * Excludes subcommands that read like queries but can write: `bugreport` and `diagnose` create
 * files, and `fsck --lost-found` writes recovered objects.
 */
const READ_ONLY_GIT_SUBCOMMANDS = new Set([
	"annotate",
	"blame",
	"cat-file",
	"check-attr",
	"check-ignore",
	"check-mailmap",
	"check-ref-format",
	"cherry",
	"count-objects",
	"describe",
	"diff",
	"diff-files",
	"diff-index",
	"diff-pairs",
	"diff-tree",
	"for-each-ref",
	"get-tar-commit-id",
	"grep",
	"last-modified",
	"log",
	"ls-files",
	"ls-remote",
	"ls-tree",
	"merge-base",
	"merge-tree",
	"name-rev",
	"patch-id",
	"range-diff",
	"rev-list",
	"rev-parse",
	"shortlog",
	"show",
	"show-branch",
	"show-index",
	"show-ref",
	"status",
	"var",
	"verify-commit",
	"verify-tag",
	"version",
	"whatchanged",
]);

export function isTriviallySafe(command: string): boolean {
	if (!SAFE_CHARACTERS.test(command)) return false;

	const words = command.trim().split(/\s+/);
	const executable = words[0];
	if (executable === undefined) return false;

	if (executable === "git") {
		const subcommand = words[1];
		return subcommand !== undefined && READ_ONLY_GIT_SUBCOMMANDS.has(subcommand);
	}

	return READ_ONLY_EXECUTABLES.has(executable);
}
