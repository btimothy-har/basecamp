/** Per-command classification: bq query, rm/chmod/chown/find, wide-search scope, dangerous shell. */

import {
	ALLOW,
	BQ_GLOBAL_FLAGS_WITH_VALUE,
	DANGEROUS_SHELL,
	GREP_SEARCH_TOOLS,
	RECURSIVE_SEARCH_TOOLS,
	type Triage,
	WIDE_ROOTS,
} from "./rules.ts";
import {
	commandBaseName,
	commandIndexAfterPrefixes,
	hasFlag,
	hasShortFlag,
	positionalArgs,
	tokenizeShellLike,
} from "./shell-lex.ts";

export function isBqQuerySegment(segment: string): boolean {
	// Match the common agent-generated forms: `bq query` and `bq --global_flag ... query`.
	// Unknown value-taking flags intentionally stop matching rather than risk blocking unrelated commands.
	const tokens = tokenizeShellLike(segment);
	const commandIndex = commandIndexAfterPrefixes(tokens);
	const executable = tokens[commandIndex];
	if (executable === undefined || commandBaseName(executable) !== "bq") return false;

	for (let index = commandIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) return false;
		if (token === "query") return true;

		if (token.startsWith("--") && token !== "--") {
			const rawFlag = token.slice(2);
			const equalsIndex = rawFlag.indexOf("=");
			const flagName = equalsIndex === -1 ? rawFlag : rawFlag.slice(0, equalsIndex);
			if (!flagName) return false;
			if (equalsIndex === -1 && BQ_GLOBAL_FLAGS_WITH_VALUE.has(flagName)) index += 1;
			continue;
		}

		if (/^-[A-Za-z]+$/.test(token)) continue;

		return false;
	}

	return false;
}

function classifyRmTokens(tokens: string[], rmIndex: number): Triage {
	let recursive = false;
	let force = false;
	let afterDoubleDash = false;

	for (const arg of tokens.slice(rmIndex + 1)) {
		if (arg === "--") {
			afterDoubleDash = true;
			continue;
		}
		if (afterDoubleDash || !arg.startsWith("-") || arg === "-") continue;
		if (arg === "--recursive") recursive = true;
		if (arg === "--force") force = true;
		if (/^-[A-Za-z]*[rR][A-Za-z]*$/.test(arg)) recursive = true;
		if (/^-[A-Za-z]*f[A-Za-z]*$/.test(arg)) force = true;
	}

	return recursive || force ? DANGEROUS_SHELL : ALLOW;
}

function hasRecursiveFlag(args: string[]): boolean {
	let afterDoubleDash = false;
	for (const arg of args) {
		if (arg === "--") {
			afterDoubleDash = true;
			continue;
		}
		if (afterDoubleDash || !arg.startsWith("-") || arg === "-") continue;
		if (arg === "--recursive") return true;
		if (/^-[A-Za-z]*R[A-Za-z]*$/.test(arg)) return true;
	}
	return false;
}

function classifyChmodChownTokens(tokens: string[], commandIndex: number): Triage {
	return hasRecursiveFlag(tokens.slice(commandIndex + 1)) ? DANGEROUS_SHELL : ALLOW;
}

function classifyFindTokens(tokens: string[], commandIndex: number): Triage {
	return tokens.slice(commandIndex + 1).includes("-delete") ? DANGEROUS_SHELL : ALLOW;
}

function wideSearchBlock(root: string): Triage {
	return {
		kind: "block",
		reason: `Wide-ranging filesystem search blocked for performance: "${root}" is a system or home root, and searching it can take many minutes. Scope the search to the project directory (e.g. "." or a subpath). Run it yourself if a full-system scan is truly required.`,
	};
}

function normalizeSearchRoot(path: string): string {
	const stripped = path.replace(/\/+$/, "");
	return stripped === "" ? "/" : stripped;
}

function firstWideSearchRoot(paths: string[]): string | null {
	for (const path of paths) {
		if (WIDE_ROOTS.has(normalizeSearchRoot(path))) return path;
	}
	return null;
}

/** Paths for pattern-first tools (grep/rg/fd): the first positional is the search pattern, the rest are roots. */
function patternFirstSearchPaths(args: string[]): string[] {
	return positionalArgs(args).slice(1);
}

/** Paths for find: search roots precede the expression, after any leading global options. */
function findSearchPaths(args: string[]): string[] {
	let index = 0;
	while (index < args.length) {
		const arg = args[index];
		if (arg === undefined) break;
		if (arg === "-H" || arg === "-L" || arg === "-P") {
			index += 1;
			continue;
		}
		if (arg === "-D") {
			index += 2;
			continue;
		}
		if (arg.startsWith("-O")) {
			index += 1;
			continue;
		}
		break;
	}

	const paths: string[] = [];
	for (; index < args.length; index += 1) {
		const arg = args[index];
		if (arg === undefined) break;
		if (arg.startsWith("-") || arg === "(" || arg === "!") break;
		paths.push(arg);
	}
	return paths;
}

export function classifySearchScopeTokens(tokens: string[], commandIndex: number): Triage {
	const executable = tokens[commandIndex];
	if (executable === undefined) return ALLOW;

	const baseName = commandBaseName(executable);
	const args = tokens.slice(commandIndex + 1);

	if (baseName === "find") {
		const root = firstWideSearchRoot(findSearchPaths(args));
		return root === null ? ALLOW : wideSearchBlock(root);
	}

	if (GREP_SEARCH_TOOLS.has(baseName)) {
		const recursive =
			hasShortFlag(args, "r") || hasShortFlag(args, "R") || hasFlag(args, ["--recursive", "--dereference-recursive"]);
		if (!recursive) return ALLOW;
		const root = firstWideSearchRoot(patternFirstSearchPaths(args));
		return root === null ? ALLOW : wideSearchBlock(root);
	}

	if (RECURSIVE_SEARCH_TOOLS.has(baseName)) {
		const root = firstWideSearchRoot(patternFirstSearchPaths(args));
		return root === null ? ALLOW : wideSearchBlock(root);
	}

	return ALLOW;
}

export function classifyDangerousShellTokens(tokens: string[], commandIndex: number): Triage {
	const executable = tokens[commandIndex];
	if (executable === undefined) return ALLOW;

	const baseName = commandBaseName(executable);
	if (baseName === "sudo") return DANGEROUS_SHELL;
	if (baseName === "rm") return classifyRmTokens(tokens, commandIndex);
	if (baseName === "dd") return DANGEROUS_SHELL;
	if (baseName.startsWith("mkfs")) return DANGEROUS_SHELL;
	if (baseName === "chmod" || baseName === "chown") return classifyChmodChownTokens(tokens, commandIndex);
	if (baseName === "find") return classifyFindTokens(tokens, commandIndex);
	if (baseName === "shred") return DANGEROUS_SHELL;
	return ALLOW;
}
