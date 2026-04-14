/**
 * Git — guards against destructive operations + PR workflows.
 *
 * Guards:
 *   Block rules gate destructive git commands (force push, ref deletion, clean).
 *   gh commands are blocked by default with an allow-list of safe operations.
 *   Workflow commands unlock specific operations for their duration.
 *
 * Commands:
 *   /pull-request [base]   — create/find draft PR, review, describe, publish
 *   /pr-comments <number>  — synthesize review findings, post as PR comments
 *   /pr-walkthrough <number> [base] — interactive step-by-step walkthrough
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
	/^gh\s+pr\s+checkout(\s|$)/,
	/^gh\s+repo\s+(view|list|clone|set-default)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

// ---------------------------------------------------------------------------
// Workflow unlock state
// ---------------------------------------------------------------------------

const unlocked = {
	prEdit: false,      // gh pr edit — /pull-request
	prComment: false,   // gh pr comment, gh api .../pulls — /pr-comments
};

function lockAll(): void {
	unlocked.prEdit = false;
	unlocked.prComment = false;
}

const PR_EDIT_RE = /^gh\s+pr\s+edit(\s|$)/;
const PR_COMMENT_RE = /^gh\s+pr\s+comment(\s|$)/;
const GH_API_PR_RE = /^gh\s+api\s+repos\/[^/]+\/[^/]+\/pulls\//;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const RESOURCES = path.resolve(__dirname, "..", "resources");

function loadTemplate(name: string, vars: Record<string, string>): string {
	let template = fs.readFileSync(path.join(RESOURCES, `${name}.md`), "utf8");
	for (const [key, value] of Object.entries(vars)) {
		template = template.replaceAll(`{{${key}}}`, value);
	}
	return template;
}

function getWorkDir(cwd: string): string {
	return process.env.BASECAMP_WORK_DIR || `/tmp/pi/${path.basename(cwd)}`;
}

async function resolvePrNumber(pi: ExtensionAPI, prArg: string | undefined, ctx: any): Promise<{ number: string; branch: string } | null> {
	if (prArg) {
		// Explicit PR number — fetch the branch name
		const result = await pi.exec("gh", [
			"pr", "view", prArg,
			"--json", "headRefName",
			"-q", ".headRefName",
		]);
		if (result.code !== 0) {
			ctx.ui.notify(`PR #${prArg} not found`, "error");
			return null;
		}
		return { number: prArg, branch: result.stdout.trim() };
	}

	// No arg — find PR for current branch
	const branch = await pi.exec("git", ["branch", "--show-current"]);
	const branchName = branch.stdout.trim();
	if (!branchName) {
		ctx.ui.notify("Not on a branch", "error");
		return null;
	}

	const existing = await pi.exec("gh", [
		"pr", "list",
		"--head", branchName,
		"--json", "number",
		"-q", ".[0].number",
	]);
	if (!existing.stdout.trim()) {
		ctx.ui.notify(`No PR found for branch ${branchName}`, "error");
		return null;
	}
	return { number: existing.stdout.trim(), branch: branchName };
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

		// Workflow overrides
		if (unlocked.prEdit && PR_EDIT_RE.test(cmd)) return;
		if (unlocked.prComment && (PR_COMMENT_RE.test(cmd) || GH_API_PR_RE.test(cmd))) return;

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

	// --- Re-lock on session boundaries ---
	pi.on("session_shutdown", async () => lockAll());
	pi.on("session_before_compact", async () => lockAll());

	// --- /pull-request [base] ---
	pi.registerCommand("pull-request", {
		description: "Review and publish a pull request",
		handler: async (args, ctx) => {
			const base = args?.trim() || "main";

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

				const urlMatch = create.stdout.match(/\/pull\/(\d+)/);
				if (!urlMatch) {
					ctx.ui.notify("Created PR but couldn't parse number from output", "error");
					return;
				}
				prNumber = urlMatch[1];
				ctx.ui.notify(`Created draft PR #${prNumber}`, "info");
			}

			unlocked.prEdit = true;
			const workDir = getWorkDir(ctx.cwd);
			pi.sendUserMessage(loadTemplate("pull-request", { PR_NUMBER: prNumber, BASE: base, WORK_DIR: workDir }));
		},
	});

	// --- /pr-comments <number> ---
	pi.registerCommand("pr-comments", {
		description: "Synthesize review findings and post as PR comments",
		handler: async (args, ctx) => {
			const pr = await resolvePrNumber(pi, args?.trim(), ctx);
			if (!pr) return;

			unlocked.prComment = true;
			const workDir = getWorkDir(ctx.cwd);
			ctx.ui.notify(`PR comments workflow for #${pr.number}`, "info");
			pi.sendUserMessage(loadTemplate("pr-comments", { PR_NUMBER: pr.number, WORK_DIR: workDir }));
		},
	});

	// --- /pr-walkthrough <number> [base] ---
	pi.registerCommand("pr-walkthrough", {
		description: "Interactive step-by-step PR walkthrough",
		handler: async (args, ctx) => {
			const parts = args?.trim().split(/\s+/) || [];
			const prArg = parts[0];
			const base = parts[1] || "main";

			const pr = await resolvePrNumber(pi, prArg, ctx);
			if (!pr) return;

			// Checkout the PR branch
			ctx.ui.notify(`Checking out PR #${pr.number} (${pr.branch})...`, "info");
			const checkout = await pi.exec("gh", ["pr", "checkout", pr.number]);
			if (checkout.code !== 0) {
				ctx.ui.notify(`Failed to checkout PR: ${checkout.stderr}`, "error");
				return;
			}

			pi.sendUserMessage(loadTemplate("pr-walkthrough", { PR_NUMBER: pr.number, BRANCH: pr.branch, BASE: base }));
		},
	});
}
