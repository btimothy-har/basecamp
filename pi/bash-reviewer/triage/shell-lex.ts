/** Shell-syntax lexing: tokenization, wrapper/flag skipping, arg helpers. */

import {
	IONICE_FLAGS_WITH_VALUE,
	NETWORK_PIPE_SHELLS,
	NICE_FLAGS_WITH_VALUE,
	SHELLS,
	SUDO_FLAGS_WITH_VALUE,
	TIME_FLAGS_WITH_VALUE,
	WRAPPER_SKIP_ONE,
} from "./rules.ts";

/**
 * End of a redirection operator starting at `start`: an optional leading `&`
 * (`&>`), the `<`/`>` run, then the suffix a shell allows (`<<-`, `>&`, `>|`).
 */
function redirectionOperatorEnd(segment: string, start: number): number {
	let end = start;
	if (segment[end] === "&") end += 1;
	while (segment[end] === "<" || segment[end] === ">") end += 1;
	const core = segment.slice(start, end);
	if (core === "<<" && segment[end] === "-") return end + 1;
	if ((core === "<" || core === ">") && (segment[end] === "&" || segment[end] === "|")) return end + 1;
	return end;
}

function isRedirectionStart(segment: string, index: number): boolean {
	const char = segment[index];
	return char === "<" || char === ">" || (char === "&" && segment[index + 1] === ">");
}

/**
 * Tokenize shell syntax, stripping quotes to normalize `g"it"` → `git`.
 *
 * Unquoted redirection operators become their own tokens, because a shell ends
 * a word at one without needing whitespace: `rm>file` is `rm` redirected, and
 * fusing it into a single token left the executable matching no known command
 * name, so the whole segment fell through to `allow`. A digit run immediately
 * before the operator is its fd prefix (`2>&1`) and stays fused to it.
 */
export function tokenizeShellLike(segment: string): string[] {
	const tokens: string[] = [];
	let word = "";
	let started = false; // distinguishes a quoted empty word ('') from no word at all
	let index = 0;

	const flush = (): void => {
		if (!started) return;
		tokens.push(word);
		word = "";
		started = false;
	};

	while (index < segment.length) {
		const char = segment[index]!;

		if (char === "\\") {
			const next = segment[index + 1];
			// A backslash before a newline is a line continuation: the shell removes
			// both characters, so they must not join the surrounding words either.
			if (next === "\n") {
				index += 2;
				continue;
			}
			if (next === "\r" && segment[index + 2] === "\n") {
				index += 3;
				continue;
			}
			if (next !== undefined) {
				word += next;
				started = true;
			}
			index += 2;
			continue;
		}

		if (char === "'") {
			const close = segment.indexOf("'", index + 1);
			word += close === -1 ? segment.slice(index + 1) : segment.slice(index + 1, close);
			started = true;
			index = close === -1 ? segment.length : close + 1;
			continue;
		}

		if (char === '"') {
			let cursor = index + 1;
			while (cursor < segment.length && segment[cursor] !== '"') {
				if (segment[cursor] === "\\" && cursor + 1 < segment.length) {
					word += segment[cursor + 1];
					cursor += 2;
					continue;
				}
				word += segment[cursor];
				cursor += 1;
			}
			started = true;
			index = cursor + 1;
			continue;
		}

		if (/\s/.test(char)) {
			flush();
			index += 1;
			continue;
		}

		if (isRedirectionStart(segment, index)) {
			let fdPrefix = "";
			if (started && /^\d+$/.test(word)) {
				fdPrefix = word;
				word = "";
				started = false;
			} else {
				flush();
			}
			const end = redirectionOperatorEnd(segment, index);
			tokens.push(fdPrefix + segment.slice(index, end));
			index = end;
			continue;
		}

		word += char;
		started = true;
		index += 1;
	}

	flush();
	return tokens;
}

export function isShellAssignment(token: string): boolean {
	return /^[A-Za-z_][A-Za-z0-9_]*=.*/.test(token);
}

export function commandBaseName(token: string): string {
	const normalized = token.replace(/\\/g, "/");
	return normalized.split("/").pop() ?? normalized;
}

export function isGitExecutable(token: string): boolean {
	return commandBaseName(token) === "git";
}

export function isGhExecutable(token: string): boolean {
	return commandBaseName(token) === "gh";
}

export function isShellExecutable(token: string): boolean {
	return SHELLS.has(commandBaseName(token));
}

export function isNetworkPipeShellExecutable(token: string): boolean {
	return NETWORK_PIPE_SHELLS.has(commandBaseName(token));
}

export function isXargsExecutable(token: string): boolean {
	return commandBaseName(token) === "xargs";
}

function skipEnvArguments(tokens: string[], startIndex: number): number {
	let index = startIndex;

	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined) return index;
		if (token === "--") return index + 1;
		if (isShellAssignment(token)) {
			index += 1;
			continue;
		}

		if (token === "-u" || token === "--unset" || token === "-C" || token === "--chdir") {
			index += 2;
			continue;
		}

		if (token.startsWith("-u") || token.startsWith("-C")) {
			index += 1;
			continue;
		}

		if (token.startsWith("--unset=") || token.startsWith("--chdir=")) {
			index += 1;
			continue;
		}

		if (token === "-i" || token === "--ignore-environment") {
			index += 1;
			continue;
		}

		break;
	}

	return index;
}

function skipFlagArguments(tokens: string[], startIndex: number, flagsWithValues: Set<string>): number {
	let index = startIndex;

	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined) return index;
		if (token === "--") return index + 1;
		if (!token.startsWith("-") || token === "-") return index;

		const equalsIndex = token.indexOf("=");
		const flagName = equalsIndex === -1 ? token : token.slice(0, equalsIndex);
		if (equalsIndex === -1 && flagsWithValues.has(flagName)) {
			index += 2;
			continue;
		}

		index += 1;
	}

	return index;
}

/**
 * Redirections may legally precede the command word (`<<EOF bash`,
 * `2>/dev/null git push`), so the command-index helpers skip them — otherwise
 * the operator sits at the executable position and every classifier misreads
 * the segment as unclassifiable.
 */
const REDIRECTION_RE = /^\d*(?:<{1,3}-?|>{1,2}|<>|>&|<&|&>{1,2}|>\|)$/;

/** Skip redirection operators and their targets; the tokenizer always emits an operator on its own. */
function skipRedirections(tokens: string[], startIndex: number): number {
	let index = startIndex;
	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined || !REDIRECTION_RE.test(token)) return index;
		index += 2;
	}
	return index;
}

function skipWrapper(tokens: string[], index: number): number | null {
	const token = tokens[index];
	if (token === undefined) return index;
	const executable = commandBaseName(token);

	if (WRAPPER_SKIP_ONE.has(executable)) return index + 1;
	if (executable === "env") return skipEnvArguments(tokens, index + 1);
	if (executable === "sudo") return skipFlagArguments(tokens, index + 1, SUDO_FLAGS_WITH_VALUE);
	if (executable === "time") return skipFlagArguments(tokens, index + 1, TIME_FLAGS_WITH_VALUE);
	if (executable === "nice") return skipFlagArguments(tokens, index + 1, NICE_FLAGS_WITH_VALUE);
	if (executable === "ionice") return skipFlagArguments(tokens, index + 1, IONICE_FLAGS_WITH_VALUE);

	return null;
}

export function commandIndexAfterAssignmentsAndEnv(tokens: string[]): number {
	let index = 0;

	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined) return index;
		if (isShellAssignment(token)) {
			index += 1;
			continue;
		}
		const afterRedirections = skipRedirections(tokens, index);
		if (afterRedirections !== index) {
			index = afterRedirections;
			continue;
		}
		if (commandBaseName(token) === "env") {
			index = skipEnvArguments(tokens, index + 1);
			continue;
		}
		break;
	}

	return index;
}

export function commandIndexAfterPrefixes(tokens: string[]): number {
	let index = 0;

	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined) return index;
		if (isShellAssignment(token)) {
			index += 1;
			continue;
		}
		const afterRedirections = skipRedirections(tokens, index);
		if (afterRedirections !== index) {
			index = afterRedirections;
			continue;
		}

		const nextIndex = skipWrapper(tokens, index);
		if (nextIndex !== null) {
			index = nextIndex;
			continue;
		}
		break;
	}

	return index;
}

export function shellScriptArgument(tokens: string[], commandIndex: number): string | null {
	for (let index = commandIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) return null;
		if (token === "-c" || /^-[A-Za-z]*c[A-Za-z]*$/.test(token)) return tokens[index + 1] ?? null;
	}

	return null;
}

export function hasFlag(args: string[], names: string[]): boolean {
	return args.some((arg) => names.includes(arg) || names.some((name) => arg.startsWith(`${name}=`)));
}

export function hasShortFlag(args: string[], letter: string): boolean {
	return args.some((arg) => new RegExp(`^-[A-Za-z]*${letter}[A-Za-z]*$`).test(arg));
}

export function positionalArgs(args: string[]): string[] {
	const result: string[] = [];
	let afterDoubleDash = false;
	for (const arg of args) {
		if (arg === "--") {
			afterDoubleDash = true;
			continue;
		}
		if (!afterDoubleDash && arg.startsWith("-")) continue;
		result.push(arg);
	}
	return result;
}
