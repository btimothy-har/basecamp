/**
 * Git — guards against destructive operations + PR workflow.
 *
 * Guards:
 *   Block rules gate destructive git commands (force push, ref deletion, clean).
 *   gh commands are blocked by default with an allow-list of safe operations.
 *   gh pr edit is unlocked during an active PR workflow.
 *
 * PR workflow:
 *   /pull-request [base] — create or find a draft PR, then hand off to the
 *   agent with a structured prompt for review, description, and publish.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Git protect — block rules
// ---------------------------------------------------------------------------

const BLOCK_RULES: { gate: RegExp; test: RegExp; reason: string }[] = [
	{ gate: /^git\s+push\b/, test: /\s(--force|--force-with-lease)(\s|$)|\s-[a-zA-Z]*f/, reason: "Force push is blocked. Ask the user to run this command themselves if needed." },
	{ gate: /^git\s+push\b/, test: /\s--delete(\s|$)|\s:[^\s]/, reason: "Deleting remote refs is blocked. Ask the user to run this command themselves if needed." },
	{ gate: /^git\s+clean\b/, test: /\s-[a-zA-Z]*f|\s--force/, reason: "git clean -f is blocked — permanently deletes untracked files. Ask the user to run this command themselves if needed." },
];

const GH_ALLOW: RegExp[] = [
	/^gh\s+issue(\s|$)/,
	/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/,
	/^gh\s+repo\s+(view|list|clone|set-default)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

// ---------------------------------------------------------------------------
// PR workflow state
// ---------------------------------------------------------------------------

let prUnlocked = false;

const PR_EDIT_PATTERN = /^gh\s+pr\s+edit(\s|$)/;

const PROMPT_PATH = path.resolve(__dirname, "..", "resources", "pull-request.md");

function loadPrompt(prNumber: string, base: string, workDir: string): string {
	const template = fs.readFileSync(PROMPT_PATH, "utf8");
	return template
		.replaceAll("{{PR_NUMBER}}", prNumber)
		.replaceAll("{{BASE}}", base)
		.replaceAll("{{WORK_DIR}}", workDir);
}

// ---------------------------------------------------------------------------
// Extension entry point
// ---------------------------------------------------------------------------

export default function (pi: ExtensionAPI) {
	// --- Git protect ---
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return;

		const cmd = event.input.command;
		if (!cmd) return;

		// PR workflow override — allow gh pr edit when unlocked
		if (prUnlocked && PR_EDIT_PATTERN.test(cmd)) return;

		// Check block rules
		for (const rule of BLOCK_RULES) {
			if (rule.gate.test(cmd) && rule.test.test(cmd)) {
				return { block: true, reason: rule.reason };
			}
		}

		// gh: block by default, allow-list overrides
		if (/^gh\s+/.test(cmd) && !GH_ALLOW.some((r) => r.test(cmd))) {
			return { block: true, reason: "This gh command is blocked. Allowed: gh issue (all), gh pr/run/repo (read-only), gh search, gh browse. Ask the user to run this command themselves if needed." };
		}
	});

	// --- PR workflow re-lock ---
	pi.on("session_shutdown", async () => { prUnlocked = false; });
	pi.on("session_before_compact", async () => { prUnlocked = false; });

	// --- /pull-request command ---
	pi.registerCommand("pull-request", {
		description: "Review and publish a pull request",
		handler: async (args, ctx) => {
			const base = args?.trim() || "main";

			// Check for existing PR on current branch
			const branch = await pi.exec("git", ["branch", "--show-current"]);
			const branchName = branch.stdout.trim();
			if (!branchName) {
				ctx.ui.notify("Not on a branch — cannot create PR", "error");
				return;
			}

			const existing = await pi.exec("gh", [
				"pr", "list",
				"--head", branchName,
				"--json", "number,url",
				"-q", ".[0]",
			]);

			let prNumber: string;

			if (existing.stdout.trim()) {
				const pr = JSON.parse(existing.stdout.trim());
				prNumber = String(pr.number);
				ctx.ui.notify(`Found existing PR #${prNumber}`, "info");
			} else {
				// Ensure branch is pushed
				const upstream = await pi.exec("git", [
					"rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}",
				]);
				if (upstream.code !== 0) {
					ctx.ui.notify("Branch has no upstream — push before creating a PR", "error");
					return;
				}

				ctx.ui.notify(`Creating draft PR against ${base}...`, "info");
				const create = await pi.exec("gh", [
					"pr", "create", "--draft",
					"--title", `WIP: ${branchName}`,
					"--body", "",
					"--base", base,
				]);

				if (create.code !== 0) {
					ctx.ui.notify(`Failed to create PR: ${create.stderr}`, "error");
					return;
				}

				// Parse PR URL from output, extract number
				const urlMatch = create.stdout.match(/\/pull\/(\d+)/);
				if (!urlMatch) {
					ctx.ui.notify("Created PR but couldn't parse number from output", "error");
					return;
				}
				prNumber = urlMatch[1];
				ctx.ui.notify(`Created draft PR #${prNumber}`, "info");
			}

			// Unlock gh pr edit and hand off to agent
			prUnlocked = true;

			const workDir = process.env.BASECAMP_WORK_DIR || `/tmp/pi/${path.basename(ctx.cwd)}`;
			const prompt = loadPrompt(prNumber, base, workDir);
			pi.sendUserMessage(prompt);
		},
	});
}
