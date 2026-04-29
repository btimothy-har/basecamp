/**
 * Git protect — guards against destructive git and gh operations.
 *
 * Block rules gate regex scopes to a command, test regex triggers the block.
 * gh commands are blocked by default with an allow-list of safe operations.
 * Workflow commands can unlock specific operations via the unlocked state.
 * Raw BigQuery query execution is blocked so agents use the file-based tool.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

// ---------------------------------------------------------------------------
// Block rules
// ---------------------------------------------------------------------------

const BLOCK_RULES: { gate: RegExp; test: RegExp; reason: string }[] = [
	{
		gate: /^git\s+push\b/,
		test: /\s(--force|--force-with-lease)(\s|$)|\s-[a-zA-Z]*f/,
		reason: "Force push is blocked. Ask the user to run this command themselves if needed.",
	},
	{
		gate: /^git\s+push\b/,
		test: /\s--delete(\s|$)|\s:[^\s]/,
		reason: "Deleting remote refs is blocked. Ask the user to run this command themselves if needed.",
	},
	{
		gate: /^git\s+clean\b/,
		test: /\s-[a-zA-Z]*f|\s--force/,
		reason:
			"git clean -f is blocked — permanently deletes untracked files. Ask the user to run this command themselves if needed.",
	},
];

const GH_ALLOW: RegExp[] = [
	/^gh\s+issue(\s|$)/,
	/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/,
	/^gh\s+pr\s+checkout(\s|$)/,
	/^gh\s+repo\s+(view|list|clone|set-default)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

// ---------------------------------------------------------------------------
// Workflow state
// ---------------------------------------------------------------------------

/** Active PR workflow — set by /pull-request, read by pr_publish tool. */
export let activePR: { number: string; base: string } | null = null;

export function setActivePR(pr: { number: string; base: string }): void {
	activePR = pr;
}

export function clearActivePR(): void {
	activePR = null;
}

export const unlocked = {
	prComment: false,
};

export function lockAll(): void {
	activePR = null;
	unlocked.prComment = false;
}

const GH_PR_MUTATE_RE = /^gh\s+pr\s+(create|edit|merge|close|ready|reopen)(\s|$)/;
const PR_COMMENT_RE = /^gh\s+pr\s+comment(\s|$)/;
const GH_API_PR_RE = /^gh\s+api\s+repos\/[^/]+\/[^/]+\/pulls\//;
const GH_RE = /^gh\s+/;

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

/** Tokenize just enough shell syntax to identify the command and flags without matching words containing bq. */
function tokenizeShellLike(segment: string): string[] {
	return (segment.match(SHELL_WORD_RE) ?? []).map((token) => token.replace(/^("|')(.*)\1$/, "$2"));
}

function isBqQuerySegment(segment: string): boolean {
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

		for (const segment of splitSegments(cmd)) {
			// Workflow overrides apply per-segment
			if (unlocked.prComment && (PR_COMMENT_RE.test(segment) || GH_API_PR_RE.test(segment))) {
				continue;
			}

			// BigQuery: block raw query execution so output goes through bq_query.
			if (isBqQuerySegment(segment)) {
				return { block: true, reason: BQ_QUERY_REASON };
			}

			// Check block rules
			for (const rule of BLOCK_RULES) {
				if (rule.gate.test(segment) && rule.test.test(segment)) {
					return { block: true, reason: rule.reason };
				}
			}

			// gh pr mutate: block with workflow-specific message
			if (GH_PR_MUTATE_RE.test(segment)) {
				return {
					block: true,
					reason: "PR mutations are blocked. The user needs to invoke /pull-request to start the PR workflow.",
				};
			}

			// gh: block by default, allow-list overrides
			if (GH_RE.test(segment) && !GH_ALLOW.some((r) => r.test(segment))) {
				return {
					block: true,
					reason:
						"This gh command is blocked. Allowed: gh issue (all), gh pr/run/repo (read-only), gh search, gh browse. Ask the user to run this command themselves if needed.",
				};
			}
		}
	});

	pi.on("session_shutdown", async () => lockAll());
	pi.on("session_before_compact", async () => lockAll());
}
