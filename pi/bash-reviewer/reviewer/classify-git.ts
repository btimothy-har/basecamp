/** git/gh segment classification. */

import {
	ALLOW,
	GH_ALLOW,
	GH_MUTATION,
	GIT_GLOBAL_FLAGS_WITH_VALUE,
	GIT_MUTATION,
	IRREVERSIBLE_REMOTE,
	READ_ONLY_COMMANDS,
	type Triage,
	WORKTREE_BLOCK,
} from "./rules.ts";
import { hasFlag, hasShortFlag, positionalArgs } from "./shell-lex.ts";

function classifyPush(args: string[]): Triage {
	const hasForce = hasFlag(args, ["--force", "--force-with-lease", "--force-if-includes"]) || hasShortFlag(args, "f");
	const hasDelete = hasFlag(args, ["--delete"]) || hasShortFlag(args, "d");
	const forceRefspec = args.some((arg) => arg.startsWith("+") && arg.length > 1);
	const refDelete = args.some((arg) => arg.startsWith(":") && arg.length > 1);
	const mirrorOrAll = hasFlag(args, ["--mirror", "--all", "--tags"]);

	if (hasForce || forceRefspec || hasDelete || refDelete || mirrorOrAll) return IRREVERSIBLE_REMOTE;
	return GIT_MUTATION;
}

function classifyBranch(args: string[]): Triage {
	const positions = positionalArgs(args);
	if (hasFlag(args, ["-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy"]) || hasShortFlag(args, "d")) {
		return GIT_MUTATION;
	}
	if (positions.length > 0 && !hasFlag(args, ["--list", "--show-current", "--contains", "--merged", "--no-merged"])) {
		return GIT_MUTATION;
	}
	return ALLOW;
}

function classifyTag(args: string[]): Triage {
	const positions = positionalArgs(args);
	if (hasFlag(args, ["-d", "--delete"])) return GIT_MUTATION;
	if (
		positions.length > 0 &&
		!hasFlag(args, ["--list", "-l", "--contains", "--merged", "--no-merged", "--points-at"])
	) {
		return GIT_MUTATION;
	}
	return ALLOW;
}

function gitSubcommandIndex(tokens: string[], gitIndex: number): number {
	let index = gitIndex + 1;
	while (index < tokens.length) {
		const token = tokens[index];
		if (token === undefined) return index;
		if (token === "--") return index + 1;
		if (!token.startsWith("-") || token === "-") return index;

		const equalsIndex = token.indexOf("=");
		const flagName = equalsIndex === -1 ? token : token.slice(0, equalsIndex);
		if (equalsIndex === -1 && GIT_GLOBAL_FLAGS_WITH_VALUE.has(flagName)) {
			index += 2;
			continue;
		}
		index += 1;
	}
	return index;
}

export function classifyGitTokens(tokens: string[], gitIndex: number): Triage {
	const subcommandIndex = gitSubcommandIndex(tokens, gitIndex);
	const subcommand = tokens[subcommandIndex];
	if (subcommand === undefined || subcommand.startsWith("-") || subcommand.startsWith("!")) return GIT_MUTATION;

	const args = tokens.slice(subcommandIndex + 1);
	if (subcommand === "push") return classifyPush(args);
	if (subcommand === "branch") return classifyBranch(args);
	if (subcommand === "tag") return classifyTag(args);
	if (subcommand === "worktree") return WORKTREE_BLOCK;
	if (READ_ONLY_COMMANDS.has(subcommand)) return ALLOW;
	return GIT_MUTATION;
}

export function classifyGhTokens(tokens: string[], ghIndex: number): Triage {
	const ghSegment = ["gh", ...tokens.slice(ghIndex + 1)].join(" ");
	return GH_ALLOW.some((pattern) => pattern.test(ghSegment)) ? ALLOW : GH_MUTATION;
}
