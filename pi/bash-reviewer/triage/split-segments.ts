/**
 * Segment splitting for triage. This is a safety control, not a lexing helper:
 * unclassified text falls through to `allow`, so anything the splitter hides
 * from the classifier bypasses both the deterministic rules and the LLM gate.
 *
 * One scanner owns both quoting state and separators. Splitting on separators
 * with a quote-blind second pass was a confirmed bypass: `X='a;b' rm -rf /z`
 * split inside the quotes, hiding `rm` behind an orphan quote. Heredocs are
 * recognized only at paren depth 0 because `$(( 1 << n ))` is an arithmetic
 * shift, not a heredoc opener — misreading it swallowed the rest of the
 * command as data. The fail-safe direction is always classify-not-drop: an
 * unterminated heredoc is rescanned as code rather than discarded.
 */

/** `<<`, an optional tab-stripping `-`, then the delimiter word up to whitespace or a shell metacharacter. */
const HEREDOC_OPENER_RE = /^<<(-?)[ \t]*([^\s;|&<>]*)/;

const COMMENT_START_RE = /[\s;|&(]/;

export type HeredocRecord = { opener: string; body: string };

export type SplitCommandResult = { segments: string[]; heredocs: HeredocRecord[] };

type PendingHeredoc = { delimiter: string; allowIndentedTerminator: boolean; opener: string | null };

/** Index just past a single-quoted run; single quotes have no escapes. */
function skipSingleQuoted(cmd: string, openIndex: number): number {
	const closeIndex = cmd.indexOf("'", openIndex + 1);
	return closeIndex === -1 ? cmd.length : closeIndex + 1;
}

/** Index just past a run where a backslash escapes the next character — double quotes and `$'…'`. */
function skipEscapableRun(cmd: string, openIndex: number, closer: string): number {
	let index = openIndex + 1;
	while (index < cmd.length) {
		const char = cmd[index];
		if (char === "\\") {
			index += 2;
			continue;
		}
		if (char === closer) return index + 1;
		index += 1;
	}
	return cmd.length;
}

function isCommentStart(cmd: string, index: number): boolean {
	const previous = cmd[index - 1];
	return previous === undefined || COMMENT_START_RE.test(previous);
}

function skipComment(cmd: string, index: number): number {
	const lineEnd = cmd.indexOf("\n", index);
	return lineEnd === -1 ? cmd.length : lineEnd;
}

/**
 * A delimiter word that a shell would accept: quoted, or a plain identifier.
 * Rejecting anything else keeps arithmetic shifts such as `$((1 << n))` from
 * swallowing the rest of the command as a heredoc body.
 */
function heredocDelimiter(word: string): string | null {
	const singleQuoted = /^'([^']*)'$/.exec(word);
	if (singleQuoted?.[1]) return singleQuoted[1];

	const doubleQuoted = /^"([^"]*)"$/.exec(word);
	if (doubleQuoted?.[1]) return doubleQuoted[1];

	return /^\\?[A-Za-z_][A-Za-z0-9_]*$/.test(word) ? word.replace(/^\\/, "") : null;
}

function heredocOpenerAt(cmd: string, index: number): { nextIndex: number; heredoc: PendingHeredoc } | null {
	if (cmd[index + 2] === "<") return null; // `<<<` is a here-string, whose word is on the same line

	const match = HEREDOC_OPENER_RE.exec(cmd.slice(index));
	const word = match?.[2];
	if (match === null || word === undefined) return null;

	const delimiter = heredocDelimiter(word);
	if (delimiter === null) return null;

	return {
		nextIndex: index + match[0].length,
		heredoc: { delimiter, allowIndentedTerminator: match[1] === "-", opener: null },
	};
}

function isHeredocTerminator(line: string, heredoc: PendingHeredoc): boolean {
	const candidate = line.replace(/\r$/, "");
	return heredoc.allowIndentedTerminator
		? candidate.trimStart() === heredoc.delimiter
		: candidate === heredoc.delimiter;
}

/** Body end and resume index for a terminated heredoc, or null when the terminator never appears. */
function findHeredocBody(
	cmd: string,
	bodyStart: number,
	heredoc: PendingHeredoc,
): { bodyEnd: number; nextIndex: number } | null {
	let index = bodyStart;

	while (index < cmd.length) {
		const lineEnd = cmd.indexOf("\n", index);
		const lineStop = lineEnd === -1 ? cmd.length : lineEnd;
		if (isHeredocTerminator(cmd.slice(index, lineStop), heredoc)) {
			return { bodyEnd: index, nextIndex: lineEnd === -1 ? cmd.length : lineEnd + 1 };
		}
		index = lineEnd === -1 ? cmd.length : lineEnd + 1;
	}

	return null;
}

/**
 * Whether `&` at this position is redirection syntax rather than a separator:
 * `2>&1`, `>&`, `&>`, `&>>`. A preceding escaped operator (`\>` / `\&`) is a
 * literal word character in bash, so the `&` after it still separates.
 */
function isRedirectionAmpersand(cmd: string, index: number): boolean {
	const previous = cmd[index - 1];
	const precededByOperator = (previous === ">" || previous === "|" || previous === "&") && cmd[index - 2] !== "\\";
	return precededByOperator || cmd[index + 1] === ">";
}

function separatorLength(cmd: string, index: number): number {
	const char = cmd[index];
	const next = cmd[index + 1];
	if (char === ";") return 1;
	if (char === "|") return next === "|" || next === "&" ? 2 : 1;
	if (char === "&") {
		if (next === "&") return 2;
		return isRedirectionAmpersand(cmd, index) ? 0 : 1;
	}
	return 0;
}

/**
 * Split a command into the segments a shell would run as separate commands,
 * plus the terminated heredocs encountered along the way. Heredoc bodies are
 * data and never appear in `segments`; each `heredocs` entry carries the
 * segment that opened it so callers can decide whether the body is executed
 * (`bash <<EOF`) or inert (`cat <<EOF`).
 */
export function splitCommand(cmd: string): SplitCommandResult {
	const segments: string[] = [];
	const heredocs: HeredocRecord[] = [];
	const pending: PendingHeredoc[] = [];
	let parenDepth = 0;
	let segmentStart = 0;
	let index = 0;

	const emitSegment = (end: number): void => {
		const text = cmd.slice(segmentStart, end).trim();
		if (!text) return;
		segments.push(text);
		for (const heredoc of pending) {
			if (heredoc.opener === null) heredoc.opener = text;
		}
	};

	// Consume the bodies of every heredoc opened on the line that just ended, in
	// the order the redirections appeared. On the first opener whose terminator
	// never appears, every remaining opener is dropped and nothing further is
	// consumed: those lines are rescanned as code (classify, don't drop).
	const consumeHeredocBodies = (bodyStart: number): number => {
		let bodyIndex = bodyStart;
		for (const heredoc of pending.splice(0)) {
			const found = findHeredocBody(cmd, bodyIndex, heredoc);
			if (found === null) break;
			heredocs.push({ opener: heredoc.opener ?? "", body: cmd.slice(bodyIndex, found.bodyEnd) });
			bodyIndex = found.nextIndex;
		}
		return bodyIndex;
	};

	while (index < cmd.length) {
		const char = cmd[index];

		if (char === "\\") {
			index += 2; // an escaped character is data — including a line continuation's newline
			continue;
		}
		if (char === "'") {
			index = skipSingleQuoted(cmd, index);
			continue;
		}
		if (char === '"') {
			index = skipEscapableRun(cmd, index, '"');
			continue;
		}
		if (char === "$" && cmd[index + 1] === "'") {
			index = skipEscapableRun(cmd, index + 1, "'");
			continue;
		}
		if (char === "#" && isCommentStart(cmd, index)) {
			index = skipComment(cmd, index);
			continue;
		}
		if (char === "(") {
			parenDepth += 1;
			index += 1;
			continue;
		}
		if (char === ")") {
			parenDepth = Math.max(0, parenDepth - 1);
			index += 1;
			continue;
		}
		if (char === "<" && cmd[index + 1] === "<" && parenDepth === 0) {
			const opener = heredocOpenerAt(cmd, index);
			if (opener === null) {
				index += 2;
				continue;
			}
			pending.push(opener.heredoc);
			index = opener.nextIndex;
			continue;
		}
		if (char === "\n") {
			emitSegment(index);
			index = consumeHeredocBodies(index + 1);
			segmentStart = index;
			continue;
		}

		const length = separatorLength(cmd, index);
		if (length > 0) {
			emitSegment(index);
			index += length;
			segmentStart = index;
			continue;
		}

		index += 1;
	}

	emitSegment(cmd.length);
	return { segments, heredocs };
}

/** Split a command on shell separators so each segment is checked independently. */
export function splitSegments(cmd: string): string[] {
	return splitCommand(cmd).segments;
}
