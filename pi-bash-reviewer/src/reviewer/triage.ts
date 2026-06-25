export type Triage =
	| { kind: "allow" }
	| { kind: "block"; reason: string }
	| { kind: "gate"; failClosed: boolean; category: string };

const ALLOW: Triage = { kind: "allow" };
const GIT_MUTATION: Triage = { kind: "gate", failClosed: false, category: "git-mutation" };
const GH_MUTATION: Triage = { kind: "gate", failClosed: false, category: "gh-mutation" };
const DANGEROUS_SHELL: Triage = { kind: "gate", failClosed: false, category: "dangerous-shell" };
const IRREVERSIBLE_REMOTE: Triage = { kind: "gate", failClosed: true, category: "irreversible-remote" };
const BQ_QUERY_BLOCK: Triage = {
	kind: "block",
	reason:
		'Raw `bq query` execution through bash is blocked. Write the SQL to a .sql file and use bq_query({ path: "..." }) instead.',
};

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

const GH_ALLOW: RegExp[] = [
	/^gh\s+issue\s+(view|list|ls|status)(\s|$)/,
	/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/,
	/^gh\s+pr\s+checkout(\s|$)/,
	/^gh\s+repo\s+(view|list|clone)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

const BQ_GLOBAL_FLAGS_WITH_VALUE = new Set([
	"api",
	"api_version",
	"apilog",
	"application_default_credential_file",
	"bigqueryrc",
	"billing_project",
	"ca_certificates_file",
	"client_id",
	"client_secret",
	"credential_file",
	"dataset_id",
	"discovery_file",
	"flagfile",
	"format",
	"httplib2_debuglevel",
	"job_id_prefix",
	"location",
	"max_rows_per_request",
	"oauth2_credential_file",
	"project_id",
	"proxy_address",
	"proxy_password",
	"proxy_port",
	"proxy_username",
	"service_account",
	"service_account_credential_file",
	"trace",
]);

const GIT_GLOBAL_FLAGS_WITH_VALUE = new Set([
	"-C",
	"-c",
	"--git-dir",
	"--work-tree",
	"--namespace",
	"--exec-path",
	"--config-env",
]);

const WRAPPER_SKIP_ONE = new Set(["command", "nohup"]);
const SUDO_FLAGS_WITH_VALUE = new Set([
	"-A",
	"-a",
	"-b",
	"-C",
	"-c",
	"-D",
	"-e",
	"-g",
	"-h",
	"-p",
	"-R",
	"-r",
	"-T",
	"-t",
	"-U",
	"-u",
	"--askpass",
	"--background",
	"--chdir",
	"--close-from",
	"--group",
	"--host",
	"--login-class",
	"--prompt",
	"--role",
	"--type",
	"--user",
	"--other-user",
]);
const NICE_FLAGS_WITH_VALUE = new Set(["-n", "--adjustment"]);
const IONICE_FLAGS_WITH_VALUE = new Set(["-c", "--class", "-n", "--classdata"]);
const SHELLS = new Set(["bash", "dash", "fish", "ksh", "sh", "zsh"]);
const NETWORK_PIPE_SHELLS = new Set(["bash", "sh", "zsh"]);
const NETWORK_FETCHERS = new Set(["curl", "wget"]);

/** Split a command on shell separators so each segment is checked independently. */
function splitSegments(cmd: string): string[] {
	return cmd
		.split(/\s*(?:&&|\|\||[;|])\s*/)
		.map((s) => s.trim())
		.filter(Boolean);
}

const SHELL_WORD_RE = /(?:[^\s"'\\]+|\\.|"(?:\\.|[^"\\])*"|'[^']*')+/g;

/** Tokenize shell syntax and strip quotes from each word to normalize `g"it"` → `git`. */
function tokenizeShellLike(segment: string): string[] {
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

function isShellAssignment(token: string): boolean {
	return /^[A-Za-z_][A-Za-z0-9_]*=.*/.test(token);
}

function commandBaseName(token: string): string {
	const normalized = token.replace(/\\/g, "/");
	return normalized.split("/").pop() ?? normalized;
}

function isGitExecutable(token: string): boolean {
	return commandBaseName(token) === "git";
}

function isGhExecutable(token: string): boolean {
	return commandBaseName(token) === "gh";
}

function isShellExecutable(token: string): boolean {
	return SHELLS.has(commandBaseName(token));
}

function isNetworkPipeShellExecutable(token: string): boolean {
	return NETWORK_PIPE_SHELLS.has(commandBaseName(token));
}

function isXargsExecutable(token: string): boolean {
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
	if (executable === "time") return skipFlagArguments(tokens, index + 1, new Set());
	if (executable === "nice") return skipFlagArguments(tokens, index + 1, NICE_FLAGS_WITH_VALUE);
	if (executable === "ionice") return skipFlagArguments(tokens, index + 1, IONICE_FLAGS_WITH_VALUE);

	return null;
}

function commandIndexAfterAssignmentsAndEnv(tokens: string[]): number {
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

function commandIndexAfterPrefixes(tokens: string[]): number {
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

function shellScriptArgument(tokens: string[], commandIndex: number): string | null {
	for (let index = commandIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) return null;
		if (token === "-c" || /^-[A-Za-z]*c[A-Za-z]*$/.test(token)) return tokens[index + 1] ?? null;
	}

	return null;
}

function triageSeverity(triage: Triage): number {
	if (triage.kind === "block") return 3;
	if (triage.kind === "gate" && triage.failClosed) return 2;
	if (triage.kind === "gate") return 1;
	return 0;
}

function mergeTriage(left: Triage, right: Triage): Triage {
	return triageSeverity(right) > triageSeverity(left) ? right : left;
}

function hasFlag(args: string[], names: string[]): boolean {
	return args.some((arg) => names.includes(arg) || names.some((name) => arg.startsWith(`${name}=`)));
}

function hasShortFlag(args: string[], letter: string): boolean {
	return args.some((arg) => new RegExp(`^-[A-Za-z]*${letter}[A-Za-z]*$`).test(arg));
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

function classifyGitTokens(tokens: string[], gitIndex: number): Triage {
	const subcommandIndex = gitSubcommandIndex(tokens, gitIndex);
	const subcommand = tokens[subcommandIndex];
	if (subcommand === undefined || subcommand.startsWith("-") || subcommand.startsWith("!")) return GIT_MUTATION;

	const args = tokens.slice(subcommandIndex + 1);
	if (subcommand === "push") return classifyPush(args);
	if (subcommand === "branch") return classifyBranch(args);
	if (subcommand === "tag") return classifyTag(args);
	if (READ_ONLY_COMMANDS.has(subcommand)) return ALLOW;
	return GIT_MUTATION;
}

function classifyGhTokens(tokens: string[], ghIndex: number): Triage {
	const ghSegment = ["gh", ...tokens.slice(ghIndex + 1)].join(" ");
	return GH_ALLOW.some((pattern) => pattern.test(ghSegment)) ? ALLOW : GH_MUTATION;
}

function isBqQuerySegment(segment: string): boolean {
	// Match the common agent-generated forms: `bq query` and `bq --global_flag ... query`.
	// Unknown value-taking flags intentionally stop matching rather than risk blocking unrelated commands.
	const tokens = tokenizeShellLike(segment);
	if (tokens[0] !== "bq") return false;

	for (let index = 1; index < tokens.length; index += 1) {
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

	return recursive && force ? DANGEROUS_SHELL : ALLOW;
}

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

	if (isGitExecutable(executable)) return mergeTriage(result, classifyGitTokens(tokens, commandIndex));
	if (isGhExecutable(executable)) return mergeTriage(result, classifyGhTokens(tokens, commandIndex));
	if (commandBaseName(executable) === "rm") return mergeTriage(result, classifyRmTokens(tokens, commandIndex));
	return result;
}

function classifyXargs(tokens: string[], xargsIndex: number, depth: number): Triage {
	let result: Triage = ALLOW;
	for (let index = xargsIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) continue;
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
	if (depth > 8) return ALLOW;

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
