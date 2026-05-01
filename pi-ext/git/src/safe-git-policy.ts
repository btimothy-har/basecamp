export type RiskLevel = "safe" | "mutating" | "high-risk";

export interface ParsedGitCommand {
	input: string;
	globalArgs: string[];
	subcommand: string;
	args: string[];
	argv: string[];
	normalizedCommand: string;
}

export interface RiskClassification {
	level: RiskLevel;
	category: string;
	requiresWorktree: boolean;
	approvalRequired: boolean;
	typedConfirmationRequired: boolean;
	details: HighRiskDetails | null;
}

export interface HighRiskDetails {
	operation: string;
	target?: string;
	flags?: string[];
	notes?: string[];
}

export type ParseResult =
	| { ok: true; command: ParsedGitCommand; risk: RiskClassification }
	| { ok: false; reason: string };

const SHELL_CONTROL_CHARS = new Set([";", "|", "&", "<", ">", "(", ")", "`", "$"]);
const WRAPPER_COMMANDS = new Set(["command", "env", "sudo", "nohup", "time", "nice", "ionice"]);
const SAFE_GLOBAL_FLAGS = new Set([
	"--no-pager",
	"--no-optional-locks",
	"--literal-pathspecs",
	"--glob-pathspecs",
	"--noglob-pathspecs",
	"--icase-pathspecs",
	"--no-replace-objects",
]);
const FORBIDDEN_GLOBAL_FLAGS = new Set([
	"--git-dir",
	"--work-tree",
	"--namespace",
	"--super-prefix",
	"--exec-path",
	"--config-env",
	"--bare",
]);
const FORBIDDEN_ARG_FLAGS = new Set([
	"--git-dir",
	"--work-tree",
	"--namespace",
	"--super-prefix",
	"--exec-path",
	"--config-env",
]);

const BUILTIN_COMMANDS = new Set([
	"add",
	"am",
	"annotate",
	"apply",
	"archive",
	"backfill",
	"bisect",
	"blame",
	"branch",
	"bugreport",
	"bundle",
	"cat-file",
	"check-attr",
	"check-ignore",
	"check-mailmap",
	"check-ref-format",
	"checkout",
	"checkout-index",
	"cherry",
	"cherry-pick",
	"clean",
	"clone",
	"column",
	"commit",
	"commit-graph",
	"commit-tree",
	"config",
	"count-objects",
	"describe",
	"diagnose",
	"diff",
	"diff-files",
	"diff-index",
	"diff-pairs",
	"diff-tree",
	"fast-export",
	"fast-import",
	"fetch",
	"filter-branch",
	"fmt-merge-msg",
	"for-each-ref",
	"format-patch",
	"fsck",
	"fsck-objects",
	"gc",
	"get-tar-commit-id",
	"grep",
	"hash-object",
	"help",
	"index-pack",
	"init",
	"init-db",
	"interpret-trailers",
	"last-modified",
	"log",
	"ls-files",
	"ls-remote",
	"ls-tree",
	"mailinfo",
	"mailsplit",
	"maintenance",
	"merge",
	"merge-base",
	"merge-file",
	"merge-index",
	"merge-ours",
	"merge-recursive",
	"merge-recursive-ours",
	"merge-recursive-theirs",
	"merge-subtree",
	"merge-tree",
	"mktag",
	"mktree",
	"multi-pack-index",
	"mv",
	"name-rev",
	"notes",
	"pack-objects",
	"pack-redundant",
	"pack-refs",
	"patch-id",
	"pickaxe",
	"prune",
	"prune-packed",
	"pull",
	"push",
	"range-diff",
	"read-tree",
	"rebase",
	"reflog",
	"refs",
	"remote",
	"repack",
	"replace",
	"replay",
	"repo",
	"rerere",
	"reset",
	"restore",
	"rev-list",
	"rev-parse",
	"revert",
	"rm",
	"shortlog",
	"show",
	"show-branch",
	"show-index",
	"show-ref",
	"sparse-checkout",
	"stage",
	"stash",
	"submodule",
	"status",
	"stripspace",
	"switch",
	"symbolic-ref",
	"tag",
	"unpack-file",
	"unpack-objects",
	"update-index",
	"update-ref",
	"update-server-info",
	"var",
	"verify-commit",
	"verify-pack",
	"verify-tag",
	"version",
	"whatchanged",
	"worktree",
	"write-tree",
]);

const DENIED_COMMANDS = new Set([
	"checkout--worker",
	"credential",
	"credential-cache",
	"credential-cache--daemon",
	"credential-store",
	"difftool",
	"fetch-pack",
	"filter-branch",
	"mergetool",
	"fsmonitor--daemon",
	"hook",
	"receive-pack",
	"remote-ext",
	"remote-fd",
	"send-pack",
	"submodule--helper",
	"upload-archive",
	"upload-archive--writer",
	"upload-pack",
]);

const READ_ONLY_COMMANDS = new Set([
	"annotate",
	"blame",
	"bugreport",
	"cat-file",
	"check-attr",
	"check-ignore",
	"check-mailmap",
	"check-ref-format",
	"cherry",
	"column",
	"count-objects",
	"describe",
	"diagnose",
	"diff",
	"diff-files",
	"diff-index",
	"diff-pairs",
	"diff-tree",
	"for-each-ref",
	"fsck",
	"fsck-objects",
	"get-tar-commit-id",
	"grep",
	"help",
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
	"verify-pack",
	"verify-tag",
	"version",
	"whatchanged",
]);

const HISTORY_REWRITE_COMMANDS = new Set([
	"am",
	"cherry-pick",
	"commit-tree",
	"fast-import",
	"rebase",
	"replace",
	"replay",
]);
const DESTRUCTIVE_PATH_COMMANDS = new Set(["checkout", "checkout-index", "clean", "read-tree", "reset", "restore"]);
const LOW_LEVEL_MUTATION_COMMANDS = new Set([
	"commit-graph",
	"gc",
	"hash-object",
	"index-pack",
	"maintenance",
	"mktag",
	"mktree",
	"multi-pack-index",
	"pack-objects",
	"pack-refs",
	"prune",
	"prune-packed",
	"repack",
	"unpack-file",
	"unpack-objects",
	"update-index",
	"update-ref",
	"update-server-info",
	"write-tree",
]);

const EXECUTION_ARG_FLAGS = new Set(["--exec", "--extcmd", "--upload-pack", "--receive-pack"]);

const EXECUTION_CONFIG_KEYS = [
	/^alias\./i,
	/^core\.sshcommand$/i,
	/^core\.pager$/i,
	/^core\.editor$/i,
	/^core\.fsmonitor$/i,
	/^core\.hookspath$/i,
	/^credential\..*helper$/i,
	/^diff\..*\.command$/i,
	/^filter\..*\.process$/i,
	/^gpg\.program$/i,
	/^gpg\.ssh\.program$/i,
	/^merge\..*\.driver$/i,
	/^mergetool\..*\.cmd$/i,
	/^pager\./i,
	/^sequence\.editor$/i,
];

type TokenizeResult = { ok: true; tokens: string[] } | { ok: false; reason: string };

type RiskInput = {
	level: RiskLevel;
	category: string;
	requiresWorktree: boolean;
	details?: HighRiskDetails | null;
};

function risk(input: RiskInput): RiskClassification {
	const highRisk = input.level === "high-risk";
	return {
		level: input.level,
		category: input.category,
		requiresWorktree: input.requiresWorktree,
		approvalRequired: true,
		typedConfirmationRequired: highRisk,
		details: input.details ?? null,
	};
}

function tokenizeShellLike(input: string): TokenizeResult {
	const tokens: string[] = [];
	let current = "";
	let tokenStarted = false;
	let quote: "single" | "double" | null = null;

	const pushToken = () => {
		if (!tokenStarted) return;
		tokens.push(current);
		current = "";
		tokenStarted = false;
	};

	for (let index = 0; index < input.length; index += 1) {
		const char = input[index]!;

		if (char === "\0" || char === "\n" || char === "\r") {
			return { ok: false, reason: "Command must be a single line" };
		}

		if (quote === "single") {
			if (char === "'") {
				quote = null;
				continue;
			}
			current += char;
			continue;
		}

		if (quote === "double") {
			if (char === '"') {
				quote = null;
				continue;
			}
			if (char === "`" || char === "$") {
				return { ok: false, reason: "Command substitution and variable expansion syntax are not allowed" };
			}
			if (char === "\\") {
				const next = input[index + 1];
				if (next === undefined) return { ok: false, reason: "Dangling escape in quoted argument" };
				if (next === "\n" || next === "\r") return { ok: false, reason: "Command must be a single line" };
				current += next;
				index += 1;
				continue;
			}
			current += char;
			continue;
		}

		if (/\s/.test(char)) {
			pushToken();
			continue;
		}

		if (SHELL_CONTROL_CHARS.has(char)) {
			return { ok: false, reason: "Shell control syntax is not allowed" };
		}

		if (char === "'") {
			tokenStarted = true;
			quote = "single";
			continue;
		}

		if (char === '"') {
			tokenStarted = true;
			quote = "double";
			continue;
		}

		if (char === "\\") {
			const next = input[index + 1];
			if (next === undefined) return { ok: false, reason: "Dangling escape in argument" };
			if (next === "\n" || next === "\r") return { ok: false, reason: "Command must be a single line" };
			current += next;
			tokenStarted = true;
			index += 1;
			continue;
		}

		current += char;
		tokenStarted = true;
	}

	if (quote) return { ok: false, reason: `Unclosed ${quote} quote` };
	pushToken();
	return { ok: true, tokens };
}

function basename(token: string): string {
	const normalized = token.replace(/\\/g, "/");
	return normalized.split("/").pop() ?? normalized;
}

function isPathExecutable(token: string): boolean {
	return token.includes("/") || token.startsWith(".");
}

function isForbiddenGlobalFlag(token: string): boolean {
	if (token === "-C" || token.startsWith("-C")) return true;
	if (token === "-c" || token.startsWith("-c")) return true;
	if (FORBIDDEN_GLOBAL_FLAGS.has(token)) return true;
	return [...FORBIDDEN_GLOBAL_FLAGS].some((flag) => token.startsWith(`${flag}=`));
}

function isForbiddenArgFlag(token: string): boolean {
	if (FORBIDDEN_ARG_FLAGS.has(token)) return true;
	return [...FORBIDDEN_ARG_FLAGS].some((flag) => token.startsWith(`${flag}=`));
}

function parseGlobalArgs(
	tokens: string[],
): { ok: true; globalArgs: string[]; subcommandIndex: number } | { ok: false; reason: string } {
	const globalArgs: string[] = [];
	let index = 1;

	while (index < tokens.length) {
		const token = tokens[index]!;
		if (!token.startsWith("-")) break;
		if (token === "--") return { ok: false, reason: "Global -- before the git subcommand is not supported" };
		if (isForbiddenGlobalFlag(token)) return { ok: false, reason: `Global git flag "${token}" is not allowed` };
		if (!SAFE_GLOBAL_FLAGS.has(token))
			return { ok: false, reason: `Global git flag "${token}" is not supported by safe_git` };
		globalArgs.push(token);
		index += 1;
	}

	return { ok: true, globalArgs, subcommandIndex: index };
}

function validateArgs(args: string[]): string | null {
	for (const arg of args) {
		if (arg.includes("\0")) return "NUL bytes are not allowed";
		if (isForbiddenArgFlag(arg)) return `Git context flag "${arg}" is not allowed`;
		if (EXECUTION_ARG_FLAGS.has(arg) || [...EXECUTION_ARG_FLAGS].some((flag) => arg.startsWith(`${flag}=`))) {
			return `Git execution option "${arg}" is not allowed`;
		}
	}
	return null;
}

function flags(args: string[]): string[] {
	return args.filter((arg) => arg.startsWith("-"));
}

function positionalArgs(args: string[]): string[] {
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

function hasFlag(args: string[], names: string[]): boolean {
	return args.some((arg) => names.includes(arg) || names.some((name) => arg.startsWith(`${name}=`)));
}

function hasShortFlag(args: string[], letter: string): boolean {
	return args.some((arg) => new RegExp(`^-[A-Za-z]*${letter}[A-Za-z]*$`).test(arg));
}

function firstConfigKey(args: string[]): string | null {
	for (const arg of positionalArgs(args)) {
		if (!arg.includes(".")) continue;
		return arg;
	}
	return null;
}

function executionSensitiveConfigKey(args: string[]): string | null {
	const key = firstConfigKey(args);
	if (!key) return null;
	return EXECUTION_CONFIG_KEYS.some((pattern) => pattern.test(key)) ? key : null;
}

function classifyConfig(args: string[]): RiskClassification | { rejected: string } {
	const sensitiveKey = executionSensitiveConfigKey(args);
	const scopeEscape = hasFlag(args, ["--global", "--system", "--file", "--blob"]);
	const getLike = hasFlag(args, ["--get", "--get-all", "--get-regexp", "--list", "-l", "--name-only", "--show-origin"]);
	const unset = hasFlag(args, ["--unset", "--unset-all", "--rename-section", "--remove-section"]);
	const setLike = unset || positionalArgs(args).length >= 2 || hasFlag(args, ["--add", "--replace-all"]);

	if (sensitiveKey && setLike) {
		return { rejected: `Config key "${sensitiveKey}" can affect command execution and is not allowed` };
	}

	if (scopeEscape && setLike) {
		return { rejected: "Mutating global, system, file, or blob config is not allowed" };
	}

	if (setLike) {
		return risk({
			level: "high-risk",
			category: "config-mutation",
			requiresWorktree: true,
			details: { operation: "config", target: firstConfigKey(args) ?? undefined, flags: flags(args) },
		});
	}

	return risk({ level: getLike || args.length > 0 ? "safe" : "safe", category: "read-only", requiresWorktree: false });
}

function classifyBranch(args: string[]): RiskClassification {
	const positions = positionalArgs(args);
	if (hasFlag(args, ["-D", "--delete"]) || hasShortFlag(args, "d")) {
		return risk({
			level: "high-risk",
			category: "branch-deletion",
			requiresWorktree: true,
			details: { operation: "delete-branch", target: positions[0], flags: flags(args) },
		});
	}
	if (hasFlag(args, ["-m", "-M", "--move", "-c", "-C", "--copy"])) {
		return risk({
			level: "mutating",
			category: "branch-mutation",
			requiresWorktree: true,
			details: { operation: "branch", target: positions[0], flags: flags(args) },
		});
	}
	if (positions.length > 0 && !hasFlag(args, ["--list", "--show-current", "--contains", "--merged", "--no-merged"])) {
		return risk({
			level: "mutating",
			category: "branch-creation",
			requiresWorktree: true,
			details: { operation: "create-branch", target: positions[0], flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifyTag(args: string[]): RiskClassification {
	const positions = positionalArgs(args);
	if (hasFlag(args, ["-d", "--delete"])) {
		return risk({
			level: "high-risk",
			category: "tag-deletion",
			requiresWorktree: true,
			details: { operation: "delete-tag", target: positions[0], flags: flags(args) },
		});
	}
	if (
		positions.length > 0 &&
		!hasFlag(args, ["--list", "-l", "--contains", "--merged", "--no-merged", "--points-at"])
	) {
		return risk({
			level: "mutating",
			category: "tag-creation",
			requiresWorktree: true,
			details: { operation: "create-tag", target: positions[0], flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifyRemote(args: string[]): RiskClassification {
	const op = positionalArgs(args)[0];
	if (["add", "remove", "rm", "rename", "set-url", "set-head", "set-branches", "prune", "update"].includes(op ?? "")) {
		return risk({
			level: "high-risk",
			category: "remote-config-mutation",
			requiresWorktree: true,
			details: { operation: "remote", target: op, flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifyStash(args: string[]): RiskClassification {
	const op = positionalArgs(args)[0] ?? "push";
	if (["list", "show", "branch"].includes(op))
		return risk({ level: "safe", category: "read-only", requiresWorktree: false });
	if (["drop", "clear"].includes(op)) {
		return risk({
			level: "high-risk",
			category: "stash-deletion",
			requiresWorktree: true,
			details: { operation: `stash ${op}`, flags: flags(args) },
		});
	}
	return risk({
		level: "mutating",
		category: "stash-mutation",
		requiresWorktree: true,
		details: { operation: `stash ${op}`, flags: flags(args) },
	});
}

function classifyNotes(args: string[]): RiskClassification {
	const op = positionalArgs(args)[0];
	if (["add", "append", "edit", "remove", "prune", "merge"].includes(op ?? "")) {
		return risk({
			level: "mutating",
			category: "notes-mutation",
			requiresWorktree: true,
			details: { operation: "notes", target: op, flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifyReflog(args: string[]): RiskClassification {
	const op = positionalArgs(args)[0];
	if (["delete", "expire"].includes(op ?? "")) {
		return risk({
			level: "high-risk",
			category: "reflog-mutation",
			requiresWorktree: true,
			details: { operation: `reflog ${op}`, flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifySymbolicRef(args: string[]): RiskClassification {
	if (hasFlag(args, ["--delete"])) {
		return risk({
			level: "high-risk",
			category: "ref-deletion",
			requiresWorktree: true,
			details: { operation: "symbolic-ref delete", target: positionalArgs(args)[0], flags: flags(args) },
		});
	}
	if (positionalArgs(args).length >= 2) {
		return risk({
			level: "high-risk",
			category: "ref-mutation",
			requiresWorktree: true,
			details: { operation: "symbolic-ref", target: positionalArgs(args)[0], flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "read-only", requiresWorktree: false });
}

function classifyPush(args: string[]): RiskClassification {
	const hasForce = hasFlag(args, ["--force", "--force-with-lease", "--force-if-includes"]) || hasShortFlag(args, "f");
	const hasDelete = hasFlag(args, ["--delete"]) || hasShortFlag(args, "d");
	const refDelete = args.find((arg) => arg.startsWith(":") && arg.length > 1);
	const mirrorOrAll = hasFlag(args, ["--mirror", "--all", "--tags"]);

	if (hasForce) {
		return risk({
			level: "high-risk",
			category: "force-push",
			requiresWorktree: true,
			details: { operation: "force-push", flags: flags(args) },
		});
	}
	if (hasDelete || refDelete) {
		return risk({
			level: "high-risk",
			category: "remote-ref-deletion",
			requiresWorktree: true,
			details: { operation: "delete-remote-ref", target: refDelete?.slice(1), flags: flags(args) },
		});
	}
	if (mirrorOrAll) {
		return risk({
			level: "high-risk",
			category: "broad-push",
			requiresWorktree: true,
			details: { operation: "push", flags: flags(args), notes: ["Push targets multiple refs"] },
		});
	}
	return risk({ level: "mutating", category: "remote-mutation", requiresWorktree: true });
}

function classifyClean(args: string[]): RiskClassification {
	if (hasFlag(args, ["--force"]) || hasShortFlag(args, "f")) {
		return risk({
			level: "high-risk",
			category: "forced-clean",
			requiresWorktree: true,
			details: { operation: "clean", flags: flags(args) },
		});
	}
	return risk({ level: "safe", category: "clean-preview", requiresWorktree: false });
}

function classifyReset(args: string[]): RiskClassification {
	if (hasFlag(args, ["--hard", "--merge", "--keep"])) {
		return risk({
			level: "high-risk",
			category: "working-tree-reset",
			requiresWorktree: true,
			details: { operation: "reset", target: positionalArgs(args)[0], flags: flags(args) },
		});
	}
	return risk({ level: "mutating", category: "index-mutation", requiresWorktree: true });
}

function classifyCheckout(args: string[]): RiskClassification {
	const hasPathspec = args.includes("--") || positionalArgs(args).some((arg) => arg.includes("/"));
	if (hasFlag(args, ["--force"]) || hasShortFlag(args, "f") || hasPathspec) {
		return risk({
			level: "high-risk",
			category: "checkout-overwrite",
			requiresWorktree: true,
			details: { operation: "checkout", target: positionalArgs(args)[0], flags: flags(args) },
		});
	}
	return risk({ level: "mutating", category: "branch-switch", requiresWorktree: true });
}

function classifyRestore(args: string[]): RiskClassification {
	const stagedOnly = hasFlag(args, ["--staged", "-S"]) && !hasFlag(args, ["--worktree", "-W", "--source", "-s"]);
	if (stagedOnly) return risk({ level: "mutating", category: "unstage", requiresWorktree: true });
	return risk({
		level: "high-risk",
		category: "restore-overwrite",
		requiresWorktree: true,
		details: { operation: "restore", target: positionalArgs(args)[0], flags: flags(args) },
	});
}

function classifyWorktree(args: string[]): RiskClassification {
	const op = positionalArgs(args)[0];
	if (["list", "repair"].includes(op ?? "list"))
		return risk({ level: "safe", category: "read-only", requiresWorktree: false });
	return risk({
		level: "high-risk",
		category: "worktree-mutation",
		requiresWorktree: true,
		details: { operation: "worktree", target: op, flags: flags(args) },
	});
}

function classifySubmodule(args: string[]): RiskClassification | { rejected: string } {
	const op = positionalArgs(args)[0];
	if (op === "foreach") return { rejected: "git submodule foreach executes commands and is not allowed" };
	if (["status", "summary"].includes(op ?? "status"))
		return risk({ level: "safe", category: "read-only", requiresWorktree: false });
	return risk({
		level: "mutating",
		category: "submodule-mutation",
		requiresWorktree: true,
		details: { operation: "submodule", target: op, flags: flags(args) },
	});
}

function classifyBisect(args: string[]): RiskClassification | { rejected: string } {
	const op = positionalArgs(args)[0];
	if (op === "run") return { rejected: "git bisect run executes commands and is not allowed" };
	return risk({
		level: "mutating",
		category: "bisect-mutation",
		requiresWorktree: true,
		details: { operation: "bisect", target: op, flags: flags(args) },
	});
}

function classifyRebase(args: string[]): RiskClassification | { rejected: string } {
	if (hasShortFlag(args, "x")) return { rejected: "git rebase --exec executes commands and is not allowed" };
	return risk({
		level: "high-risk",
		category: "history-mutation",
		requiresWorktree: true,
		details: { operation: "rebase", flags: flags(args) },
	});
}

function classifySpecialCommand(subcommand: string, args: string[]): RiskClassification | { rejected: string } | null {
	switch (subcommand) {
		case "bisect":
			return classifyBisect(args);
		case "branch":
			return classifyBranch(args);
		case "config":
			return classifyConfig(args);
		case "push":
			return classifyPush(args);
		case "clean":
			return classifyClean(args);
		case "reset":
			return classifyReset(args);
		case "checkout":
			return classifyCheckout(args);
		case "restore":
			return classifyRestore(args);
		case "remote":
			return classifyRemote(args);
		case "rebase":
			return classifyRebase(args);
		case "stash":
			return classifyStash(args);
		case "tag":
			return classifyTag(args);
		case "notes":
			return classifyNotes(args);
		case "reflog":
			return classifyReflog(args);
		case "symbolic-ref":
			return classifySymbolicRef(args);
		case "worktree":
			return classifyWorktree(args);
		case "submodule":
			return classifySubmodule(args);
		default:
			return null;
	}
}

function classifyCommand(subcommand: string, args: string[]): RiskClassification | { rejected: string } {
	if (DENIED_COMMANDS.has(subcommand)) return { rejected: `git ${subcommand} is not allowed by safe_git policy` };
	if (!BUILTIN_COMMANDS.has(subcommand)) return { rejected: `Unknown or unsupported git subcommand "${subcommand}"` };

	const special = classifySpecialCommand(subcommand, args);
	if (special) return special;

	if (READ_ONLY_COMMANDS.has(subcommand))
		return risk({ level: "safe", category: "read-only", requiresWorktree: false });

	if (HISTORY_REWRITE_COMMANDS.has(subcommand)) {
		return risk({
			level: "high-risk",
			category: "history-mutation",
			requiresWorktree: true,
			details: { operation: subcommand, flags: flags(args) },
		});
	}

	if (DESTRUCTIVE_PATH_COMMANDS.has(subcommand)) {
		return risk({
			level: "high-risk",
			category: "working-tree-mutation",
			requiresWorktree: true,
			details: { operation: subcommand, flags: flags(args) },
		});
	}

	if (LOW_LEVEL_MUTATION_COMMANDS.has(subcommand)) {
		return risk({
			level: "high-risk",
			category: "low-level-repo-mutation",
			requiresWorktree: true,
			details: { operation: subcommand, flags: flags(args) },
		});
	}

	return risk({
		level: "mutating",
		category: "local-mutation",
		requiresWorktree: true,
		details: { operation: subcommand, flags: flags(args) },
	});
}

function quoteArg(arg: string): string {
	if (/^[A-Za-z0-9_@%+=:,./{}-]+$/.test(arg)) return arg;
	return `'${arg.replace(/'/g, "'\\''")}'`;
}

export function parseGitCommand(input: string): ParseResult {
	const trimmed = input.trim();
	if (!trimmed) return { ok: false, reason: "Empty command" };

	const tokenized = tokenizeShellLike(trimmed);
	if (!tokenized.ok) return tokenized;
	const { tokens } = tokenized;
	if (tokens.length === 0) return { ok: false, reason: "Empty command" };

	const executable = tokens[0]!;
	if (WRAPPER_COMMANDS.has(executable) || WRAPPER_COMMANDS.has(basename(executable))) {
		return { ok: false, reason: `Command wrapper "${executable}" is not allowed` };
	}
	if (isPathExecutable(executable))
		return { ok: false, reason: 'Use "git" directly; path-qualified executables are not allowed' };
	if (executable !== "git") return { ok: false, reason: `Command must start with "git", got "${executable}"` };

	const globalParse = parseGlobalArgs(tokens);
	if (!globalParse.ok) return globalParse;

	const subcommand = tokens[globalParse.subcommandIndex];
	if (!subcommand) return { ok: false, reason: "No git subcommand provided" };
	if (subcommand.startsWith("-")) return { ok: false, reason: `Expected subcommand, got flag "${subcommand}"` };
	if (subcommand.startsWith("!")) return { ok: false, reason: "External git aliases are not allowed" };

	const args = tokens.slice(globalParse.subcommandIndex + 1);
	const argError = validateArgs(args);
	if (argError) return { ok: false, reason: argError };

	const classification = classifyCommand(subcommand, args);
	if ("rejected" in classification) return { ok: false, reason: classification.rejected };

	const argv = ["git", ...globalParse.globalArgs, subcommand, ...args];
	return {
		ok: true,
		command: {
			input: trimmed,
			globalArgs: globalParse.globalArgs,
			subcommand,
			args,
			argv,
			normalizedCommand: argv.map(quoteArg).join(" "),
		},
		risk: classification,
	};
}

export function formatRiskSummary(risk: RiskClassification): string {
	const parts = [`${risk.level} (${risk.category})`];
	if (risk.requiresWorktree) parts.push("requires worktree");
	if (risk.typedConfirmationRequired) parts.push("typed confirmation");
	return parts.join(", ");
}

export function isHighRisk(risk: RiskClassification): boolean {
	return risk.level === "high-risk";
}
