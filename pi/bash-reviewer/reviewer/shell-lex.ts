/** Shell-syntax lexing: segment splitting, tokenization, wrapper/flag skipping, arg helpers. */

import {
	IONICE_FLAGS_WITH_VALUE,
	NETWORK_PIPE_SHELLS,
	NICE_FLAGS_WITH_VALUE,
	SHELLS,
	SUDO_FLAGS_WITH_VALUE,
	TIME_FLAGS_WITH_VALUE,
	WRAPPER_SKIP_ONE,
} from "./rules.ts";

/** Split a command on shell separators so each segment is checked independently. */
export function splitSegments(cmd: string): string[] {
	return cmd
		.split(/\s*(?:&&|\|\||[;|])\s*/)
		.map((s) => s.trim())
		.filter(Boolean);
}

const SHELL_WORD_RE = /(?:[^\s"'\\]+|\\.|"(?:\\.|[^"\\])*"|'[^']*')+/g;

/** Tokenize shell syntax and strip quotes from each word to normalize `g"it"` → `git`. */
export function tokenizeShellLike(segment: string): string[] {
	return (segment.match(SHELL_WORD_RE) ?? []).map((token) => {
		let result = "";
		let i = 0;
		while (i < token.length) {
			const ch = token[i]!;
			if (ch === "\\" && i + 1 < token.length) {
				result += token[i + 1];
				i += 2;
			} else if (ch === "'") {
				const end = token.indexOf("'", i + 1);
				result += end === -1 ? token.slice(i + 1) : token.slice(i + 1, end);
				i = end === -1 ? token.length : end + 1;
			} else if (ch === '"') {
				let j = i + 1;
				while (j < token.length && token[j] !== '"') {
					if (token[j] === "\\" && j + 1 < token.length) {
						result += token[j + 1];
						j += 2;
					} else {
						result += token[j];
						j += 1;
					}
				}
				i = j + 1;
			} else {
				result += ch;
				i += 1;
			}
		}
		return result;
	});
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
