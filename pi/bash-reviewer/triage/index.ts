/**
 * Static command triage — composes the segment/nesting walk over the
 * classifiers in classify-git.ts and classify-commands.ts, using the shell
 * lexing in shell-lex.ts and the verdicts/tables in rules.ts.
 */

import { classifyDangerousShellTokens, classifySearchScopeTokens, isBqQuerySegment } from "./classify-commands.ts";
import { classifyGhTokens, classifyGitTokens } from "./classify-git.ts";
import { ALLOW, BQ_QUERY_BLOCK, DANGEROUS_SHELL, mergeTriage, NETWORK_FETCHERS, type Triage } from "./rules.ts";
import {
	commandBaseName,
	commandIndexAfterAssignmentsAndEnv,
	commandIndexAfterPrefixes,
	isGhExecutable,
	isGitExecutable,
	isNetworkPipeShellExecutable,
	isShellExecutable,
	isXargsExecutable,
	shellScriptArgument,
	splitSegments,
	tokenizeShellLike,
} from "./shell-lex.ts";

export type { Triage } from "./rules.ts";

function directExecutableIndex(tokens: string[]): number {
	return commandIndexAfterPrefixes(tokens);
}

function directExecutableIndexWithoutSudoSkipping(tokens: string[]): number {
	return commandIndexAfterAssignmentsAndEnv(tokens);
}

function classifyDirectSegment(tokens: string[]): Triage {
	let result: Triage = ALLOW;
	const sudoCandidate = tokens[directExecutableIndexWithoutSudoSkipping(tokens)];
	if (sudoCandidate !== undefined && commandBaseName(sudoCandidate) === "sudo") {
		result = mergeTriage(result, DANGEROUS_SHELL);
	}

	const commandIndex = directExecutableIndex(tokens);
	const executable = tokens[commandIndex];
	if (executable === undefined) return result;

	result = mergeTriage(result, classifyDangerousShellTokens(tokens, commandIndex));
	result = mergeTriage(result, classifySearchScopeTokens(tokens, commandIndex));
	if (isGitExecutable(executable)) return mergeTriage(result, classifyGitTokens(tokens, commandIndex));
	if (isGhExecutable(executable)) return mergeTriage(result, classifyGhTokens(tokens, commandIndex));
	return result;
}

function classifyXargs(tokens: string[], xargsIndex: number, depth: number): Triage {
	let result: Triage = ALLOW;
	for (let index = xargsIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) continue;
		result = mergeTriage(result, classifyDangerousShellTokens(tokens, index));
		result = mergeTriage(result, classifySearchScopeTokens(tokens, index));
		if (isGitExecutable(token)) result = mergeTriage(result, classifyGitTokens(tokens, index));
		if (isGhExecutable(token)) result = mergeTriage(result, classifyGhTokens(tokens, index));
		if (isShellExecutable(token)) {
			const script = shellScriptArgument(tokens, index);
			if (script !== null) result = mergeTriage(result, triageCommandInternal(script, depth + 1));
		}
	}
	return result;
}

function classifyNestedSegment(tokens: string[], depth: number): Triage {
	const commandIndex = directExecutableIndex(tokens);
	const executable = tokens[commandIndex];
	if (executable === undefined) return ALLOW;

	if (isShellExecutable(executable)) {
		const script = shellScriptArgument(tokens, commandIndex);
		return script === null ? ALLOW : triageCommandInternal(script, depth + 1);
	}

	if (isXargsExecutable(executable)) return classifyXargs(tokens, commandIndex, depth);
	return ALLOW;
}

function isShellStdinSegment(segment: string): boolean {
	const tokens = tokenizeShellLike(segment);
	const commandIndex = directExecutableIndex(tokens);
	const executable = tokens[commandIndex];
	return (
		executable !== undefined &&
		isNetworkPipeShellExecutable(executable) &&
		shellScriptArgument(tokens, commandIndex) === null
	);
}

function isNetworkFetchSegment(segment: string): boolean {
	const tokens = tokenizeShellLike(segment);
	const commandIndex = directExecutableIndex(tokens);
	const executable = tokens[commandIndex];
	return executable !== undefined && NETWORK_FETCHERS.has(commandBaseName(executable));
}

function findNetworkFetchPipedToShell(cmd: string): boolean {
	const parts = cmd.split("|");
	let sawNetworkFetch = false;

	for (const part of parts) {
		const segment = part.trim();
		if (!segment) continue;
		if (sawNetworkFetch && isShellStdinSegment(segment)) return true;
		if (isNetworkFetchSegment(segment)) sawNetworkFetch = true;
	}

	return false;
}

function commandSubstitutionBodies(cmd: string): string[] {
	const bodies: string[] = [];
	for (const match of cmd.matchAll(/\$\(([^)]+)\)/g)) {
		const body = match[1];
		if (body !== undefined) bodies.push(body);
	}
	for (const match of cmd.matchAll(/`([^`]+)`/g)) {
		const body = match[1];
		if (body !== undefined) bodies.push(body);
	}
	return bodies;
}

function classifySegment(segment: string, depth: number): Triage {
	if (isBqQuerySegment(segment)) return BQ_QUERY_BLOCK;

	const tokens = tokenizeShellLike(segment);
	return mergeTriage(classifyDirectSegment(tokens), classifyNestedSegment(tokens, depth));
}

function triageCommandInternal(command: string, depth: number): Triage {
	if (depth > 8)
		return { kind: "block", reason: "Command nesting is too deep to analyze safely; simplify the command." };

	let result: Triage = ALLOW;

	for (const body of commandSubstitutionBodies(command)) {
		result = mergeTriage(result, triageCommandInternal(body, depth + 1));
	}

	if (findNetworkFetchPipedToShell(command)) result = mergeTriage(result, DANGEROUS_SHELL);

	for (const segment of splitSegments(command)) {
		result = mergeTriage(result, classifySegment(segment, depth));
	}

	return result;
}

export function triageCommand(command: string): Triage {
	return triageCommandInternal(command, 0);
}
