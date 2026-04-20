/**
 * Git protect — guards against destructive git and gh operations.
 *
 * Block rules gate regex scopes to a command, test regex triggers the block.
 * gh commands are blocked by default with an allow-list of safe operations.
 * Workflow commands can unlock specific operations via the unlocked state.
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

/** Split a command on shell separators so each segment is checked independently. */
function splitSegments(cmd: string): string[] {
	return cmd
		.split(/\s*(?:&&|\|\||[;|])\s*/)
		.map((s) => s.trim())
		.filter(Boolean);
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
