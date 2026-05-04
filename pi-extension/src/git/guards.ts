/**
 * Git protect — routes git through safe_git and guards gh/bq operations.
 *
 * gh commands are blocked by default with an allow-list of safe operations.
 * Workflow commands can unlock specific operations via the unlocked state.
 * Raw BigQuery query execution is blocked so agents use the file-based tool.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

// ---------------------------------------------------------------------------
// Git block reason
// ---------------------------------------------------------------------------

const GIT_BLOCKED_REASON =
	'All git commands are blocked through bash. Use safe_git({ command: "git ...", reason: "..." }) instead. ' +
	"Commands outside the approval blocklist execute automatically; blocklisted destructive operations require user approval.";

const GH_ALLOW: RegExp[] = [
	/^gh\s+issue\s+(view|list|ls|status)(\s|$)/,
	/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/,
	/^gh\s+pr\s+checkout(\s|$)/,
	/^gh\s+repo\s+(view|list|clone)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

// ---------------------------------------------------------------------------
// Workflow state
// ---------------------------------------------------------------------------

/** Active PR workflow — set by /create-pr, read by publish_pr tool. */
export let activePR: { number: string; base: string } | null = null;

export function setActivePR(pr: { number: string; base: string }): void {
	activePR = pr;
}

export function clearActivePR(): void {
	activePR = null;
}

/** Active issue draft workflow — set by /create-issue, read by issue workflow tools. */
export let activeIssueDraft: { draftPath: string; topic: string } | null = null;

export function setActiveIssueDraft(draft: { draftPath: string; topic: string }): void {
	activeIssueDraft = draft;
}

export function clearActiveIssueDraft(): void {
	activeIssueDraft = null;
}

export const unlocked = {
	prComment: false,
};

export function lockAll(): void {
	activePR = null;
	activeIssueDraft = null;
	unlocked.prComment = false;
}

const GH_PR_MUTATE_RE = /^gh\s+pr\s+(create|edit|merge|close|ready|reopen)(\s|$)/;
const GH_ISSUE_MUTATE_RE =
	/^gh\s+issue\s+(create|edit|comment|close|reopen|delete|transfer|lock|unlock|pin|unpin|develop|new)(\s|$)/;
const PR_COMMENT_RE = /^gh\s+pr\s+comment(\s|$)/;
const GH_API_PR_RE = /^gh\s+api\s+repos\/[^/]+\/[^/]+\/pulls\//;
const GH_RE = /^gh\s+/;
const GH_MUTATION_LITERAL_RE =
	/(?:^|[^\w./-])(gh\s+(?:(?:pr)\s+(?:create|edit|merge|close|ready|reopen|comment)|(?:issue)\s+(?:create|edit|comment|close|reopen|delete|transfer|lock|unlock|pin|unpin|develop|new)))(?=\s|$)/;

const BQ_QUERY_REASON =
	'Raw `bq query` execution through bash is blocked. Write the SQL to a .sql file and use bq_query({ path: "..." }) instead.';

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

function isGhExecutable(token: string): boolean {
	return commandBaseName(token) === "gh";
}

function isGitExecutable(token: string): boolean {
	return commandBaseName(token) === "git";
}

function isShellExecutable(token: string): boolean {
	return ["bash", "dash", "fish", "ksh", "sh", "zsh"].includes(commandBaseName(token));
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

const WRAPPER_SKIP_ONE = new Set(["command", "sudo", "nohup", "time", "nice", "ionice"]);

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
		if (WRAPPER_SKIP_ONE.has(commandBaseName(token))) {
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

function normalizeGhSegment(segment: string): string | null {
	const tokens = tokenizeShellLike(segment);
	const index = commandIndexAfterPrefixes(tokens);
	const executable = tokens[index];
	if (executable === undefined || !isGhExecutable(executable)) return null;

	return ["gh", ...tokens.slice(index + 1)].join(" ");
}

function normalizeGitSegment(segment: string): string | null {
	const tokens = tokenizeShellLike(segment);
	const index = commandIndexAfterPrefixes(tokens);
	const executable = tokens[index];
	if (executable === undefined || !isGitExecutable(executable)) return null;

	return ["git", ...tokens.slice(index + 1)].join(" ");
}

function shellScriptArgument(tokens: string[], commandIndex: number): string | null {
	for (let index = commandIndex + 1; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined) return null;
		if (token === "-c" || /^-[A-Za-z]*c[A-Za-z]*$/.test(token)) return tokens[index + 1] ?? null;
	}

	return null;
}

function literalGhMutationSegment(text: string): string | null {
	return text.match(GH_MUTATION_LITERAL_RE)?.[1] ?? null;
}

function findGhMutationFromTokens(tokens: string[], startIndex: number): string | null {
	for (let index = startIndex; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token === undefined || !isGhExecutable(token)) continue;

		const ghSegment = ["gh", ...tokens.slice(index + 1)].join(" ");
		if (GH_PR_MUTATE_RE.test(ghSegment) || GH_ISSUE_MUTATE_RE.test(ghSegment) || PR_COMMENT_RE.test(ghSegment)) {
			return ghSegment;
		}
	}

	return null;
}

function findNestedGhMutationSegment(segment: string): string | null {
	const tokens = tokenizeShellLike(segment);
	const commandIndex = commandIndexAfterPrefixes(tokens);
	const executable = tokens[commandIndex];
	if (executable === undefined) return null;

	if (isShellExecutable(executable)) {
		const script = shellScriptArgument(tokens, commandIndex);
		return script ? literalGhMutationSegment(script) : null;
	}

	if (isXargsExecutable(executable)) return findGhMutationFromTokens(tokens, commandIndex + 1);

	return null;
}

function isShellStdinSegment(segment: string): boolean {
	const tokens = tokenizeShellLike(segment);
	const commandIndex = commandIndexAfterPrefixes(tokens);
	const executable = tokens[commandIndex];
	return (
		executable !== undefined && isShellExecutable(executable) && shellScriptArgument(tokens, commandIndex) === null
	);
}

function findPipedGhMutationSegment(cmd: string): string | null {
	const parts = cmd.split("|");
	let left = "";

	for (let index = 0; index < parts.length - 1; index += 1) {
		const part = parts[index];
		if (part === undefined) continue;
		left = left ? `${left}|${part}` : part;

		const right = parts[index + 1];
		if (right === undefined || !isShellStdinSegment(right.trim())) continue;

		const mutation = literalGhMutationSegment(left);
		if (mutation) return mutation;
	}

	return null;
}

function ghMutationBlockReason(ghSegment: string): string | null {
	if (GH_PR_MUTATE_RE.test(ghSegment) || PR_COMMENT_RE.test(ghSegment)) {
		return "PR mutations are blocked. The user needs to invoke /create-pr to start the PR workflow.";
	}

	if (GH_ISSUE_MUTATE_RE.test(ghSegment)) {
		return "Issue mutations are blocked. Invoke /create-issue for new issue creation; ask the user to run existing-issue mutations themselves if needed.";
	}

	return null;
}

function hasGitInTokens(tokens: string[], startIndex: number): boolean {
	for (let index = startIndex; index < tokens.length; index += 1) {
		const token = tokens[index];
		if (token !== undefined && isGitExecutable(token)) return true;
	}
	return false;
}

function hasDirectGitCommand(segment: string): boolean {
	const gitSegment = normalizeGitSegment(segment);
	if (gitSegment !== null) return true;

	const tokens = tokenizeShellLike(segment);
	const commandIndex = commandIndexAfterAssignmentsAndEnv(tokens);
	const executable = tokens[commandIndex];
	return executable !== undefined && WRAPPER_SKIP_ONE.has(commandBaseName(executable))
		? hasGitInTokens(tokens, commandIndex + 1)
		: false;
}

function hasNestedGitCommand(segment: string): boolean {
	const tokens = tokenizeShellLike(segment);
	const commandIndex = commandIndexAfterPrefixes(tokens);
	const executable = tokens[commandIndex];
	if (executable === undefined) return false;

	if (isShellExecutable(executable)) {
		const script = shellScriptArgument(tokens, commandIndex);
		if (!script) return false;
		for (const scriptSegment of splitSegments(script)) {
			if (hasDirectGitCommand(scriptSegment)) return true;
			if (hasNestedGitCommand(scriptSegment)) return true;
		}
		return false;
	}

	if (isXargsExecutable(executable)) {
		return hasGitInTokens(tokens, commandIndex + 1);
	}

	return false;
}

/** Detect command substitution containing git: `$(git ...)` or backticks. Pre-split check preserves shell quoting. */
function hasCommandSubstitutionGit(cmd: string): boolean {
	const dollarMatch = cmd.match(/\$\(([^)]+)\)/g) ?? [];
	const backtickMatch = cmd.match(/`([^`]+)`/g) ?? [];
	for (const m of dollarMatch) {
		const inner = m.slice(2, -1);
		for (const seg of splitSegments(inner)) {
			if (hasDirectGitCommand(seg) || hasNestedGitCommand(seg)) return true;
		}
	}
	for (const m of backtickMatch) {
		const inner = m.slice(1, -1);
		for (const seg of splitSegments(inner)) {
			if (hasDirectGitCommand(seg) || hasNestedGitCommand(seg)) return true;
		}
	}
	return false;
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

// ---------------------------------------------------------------------------
// Register
// ---------------------------------------------------------------------------

export function registerGuards(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return;

		const cmd = event.input.command;
		if (!cmd) return;

		const pipedGhMutation = findPipedGhMutationSegment(cmd);
		if (pipedGhMutation) {
			const reason = ghMutationBlockReason(pipedGhMutation);
			if (reason) return { block: true, reason };
		}

		if (hasCommandSubstitutionGit(cmd)) {
			return { block: true, reason: GIT_BLOCKED_REASON };
		}

		// Must run before splitSegments because quoted shell scripts can contain separators.
		if (hasNestedGitCommand(cmd)) {
			return { block: true, reason: GIT_BLOCKED_REASON };
		}

		for (const segment of splitSegments(cmd)) {
			const ghSegment = normalizeGhSegment(segment);

			// Workflow overrides apply per-segment
			if (unlocked.prComment && ghSegment && (PR_COMMENT_RE.test(ghSegment) || GH_API_PR_RE.test(ghSegment))) {
				continue;
			}

			// BigQuery: block raw query execution so output goes through bq_query.
			if (isBqQuerySegment(segment)) {
				return { block: true, reason: BQ_QUERY_REASON };
			}

			if (hasDirectGitCommand(segment)) {
				return { block: true, reason: GIT_BLOCKED_REASON };
			}

			if (hasNestedGitCommand(segment)) {
				return { block: true, reason: GIT_BLOCKED_REASON };
			}

			if (!ghSegment) {
				const nestedGhMutation = findNestedGhMutationSegment(segment);
				if (nestedGhMutation) {
					const reason = ghMutationBlockReason(nestedGhMutation);
					if (reason) return { block: true, reason };
				}
				continue;
			}

			// gh mutations: block with workflow-specific message
			const mutationReason = ghMutationBlockReason(ghSegment);
			if (mutationReason) return { block: true, reason: mutationReason };

			// gh: block by default, allow-list overrides
			if (GH_RE.test(ghSegment) && !GH_ALLOW.some((r) => r.test(ghSegment))) {
				return {
					block: true,
					reason:
						"This gh command is blocked. Allowed: gh issue view/list/ls/status, gh pr/run/repo (read-only), gh search, gh browse. Ask the user to run this command themselves if needed.",
				};
			}
		}
	});

	pi.on("session_shutdown", async () => lockAll());
	pi.on("session_before_compact", async () => lockAll());
}
