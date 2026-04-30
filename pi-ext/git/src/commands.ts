/**
 * Git commands — PR, issue, and git workflow commands.
 *
 *   /create-pr [base]               — create/find draft PR, review, describe, publish
 *   /create-issue [topic]           — draft and publish a GitHub issue through review
 *   /pr-comments [number]           — synthesize review findings, post as PR comments
 *   /pr-walkthrough [number] [base] — interactive step-by-step walkthrough
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { exec } from "../../platform/exec";
import { activeIssueDraft, setActiveIssueDraft, setActivePR, unlocked } from "./guards";
import { createIssueDraftPath, getScratchDir, loadTemplate, resolvePrNumber } from "./utils";

type PushResult = "pushed" | "up-to-date" | "cancelled" | "diverged" | "failed";

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

async function ensurePushed(pi: ExtensionAPI, branchName: string, ctx: any): Promise<PushResult> {
	const upstream = await exec(pi, "git", ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]);

	if (upstream.code !== 0) {
		const confirmed = await ctx.ui.confirm("Push to origin?", `Push ${branchName} and set upstream?`);
		if (!confirmed) return "cancelled";

		const push = await exec(pi, "git", ["push", "-u", "origin", branchName]);
		return push.code === 0 ? "pushed" : "failed";
	}

	const counts = await exec(pi, "git", ["rev-list", "--left-right", "--count", "@{u}...HEAD"]);
	if (counts.code !== 0) return "failed";

	const parts = counts.stdout.trim().split(/\s+/).map(Number);
	const behind = parts[0] ?? 0;
	const ahead = parts[1] ?? 0;
	if (ahead === 0) return "up-to-date";

	if (behind > 0) {
		ctx.ui.notify(
			`Branch has diverged from upstream (${ahead} ahead, ${behind} behind). Resolve manually with rebase or force push.`,
			"error",
		);
		return "diverged";
	}

	const confirmed = await ctx.ui.confirm("Push to origin?", `Push ${ahead} commit${ahead > 1 ? "s" : ""} to origin?`);
	if (!confirmed) return "cancelled";

	const push = await exec(pi, "git", ["push"]);
	return push.code === 0 ? "pushed" : "failed";
}

export function registerCommands(pi: ExtensionAPI): void {
	// --- /create-pr [base] ---
	pi.registerCommand("create-pr", {
		description: "Create, review, and publish a pull request",
		handler: async (args, ctx) => {
			const base = args?.trim() || "main";

			const branch = await exec(pi, "git", ["branch", "--show-current"]);
			const branchName = branch.stdout.trim();
			if (!branchName) {
				ctx.ui.notify("Not on a branch — cannot create PR", "error");
				return;
			}

			// Collect context upfront before any git operations
			let reviewContext = "";
			if (await ctx.ui.confirm("Add context?", "Add review context for this PR?")) {
				const input = await ctx.ui.input("PR context", "");
				reviewContext = input || "";
			}

			const existing = await exec(pi, "gh", ["pr", "list", "--head", branchName, "--json", "number,url", "-q", ".[0]"]);

			let prNumber: string;

			if (existing.stdout.trim()) {
				const pr = JSON.parse(existing.stdout.trim());
				prNumber = String(pr.number);
				ctx.ui.notify(`Found existing PR #${prNumber}`, "info");

				const pushResult = await ensurePushed(pi, branchName, ctx);
				if (pushResult === "cancelled" || pushResult === "diverged" || pushResult === "failed") return;
			} else {
				const pushResult = await ensurePushed(pi, branchName, ctx);
				if (pushResult === "failed") {
					ctx.ui.notify("Failed to push — cannot create PR", "error");
					return;
				}
				if (pushResult === "cancelled") {
					ctx.ui.notify("Push cancelled — cannot create PR without upstream", "error");
					return;
				}
				if (pushResult === "diverged") return;

				ctx.ui.notify(`Creating draft PR against ${base}...`, "info");
				const create = await exec(pi, "gh", [
					"pr",
					"create",
					"--draft",
					"--title",
					`WIP: ${branchName}`,
					"--body",
					"",
					"--base",
					base,
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
				prNumber = urlMatch[1]!;
				ctx.ui.notify(`Created draft PR #${prNumber}`, "info");
			}

			setActivePR({ number: prNumber, base });
			const reviewContextLine = reviewContext ? `\n- Review context: ${reviewContext}` : "";
			pi.sendUserMessage(`Continue the /create-pr workflow.

Runtime context:
- PR number: ${prNumber}
- Base branch: ${base}
- Current branch: ${branchName}${reviewContextLine}

First call skill({ name: "pull-request" }) before continuing.`);
		},
	});

	// --- /create-issue [topic] ---
	pi.registerCommand("create-issue", {
		description: "Draft and publish a GitHub issue through review",
		handler: async (args, ctx) => {
			if (!ctx.hasUI) {
				ctx.ui.notify("/create-issue requires an interactive UI. Run it from an interactive session.", "error");
				return;
			}

			if (pi.getFlag("read-only") === true) {
				ctx.ui.notify("/create-issue is disabled in read-only mode.", "error");
				return;
			}

			if (activeIssueDraft) {
				const confirmed = await ctx.ui.confirm(
					"Replace active issue draft?",
					`An issue draft is already active at ${activeIssueDraft.draftPath}. Replace it?`,
				);
				if (!confirmed) return;
			}

			const topicArg = args?.trim();
			const topic = topicArg || (await ctx.ui.input("Issue topic", ""))?.trim();

			if (!topic) {
				ctx.ui.notify("Issue topic required. Usage: /create-issue <topic>", "error");
				return;
			}

			let draftPath: string;
			try {
				draftPath = createIssueDraftPath(ctx.cwd);
			} catch (error) {
				ctx.ui.notify(`Failed to prepare issue draft directory: ${errorMessage(error)}`, "error");
				return;
			}

			setActiveIssueDraft({ draftPath, topic });
			ctx.ui.notify(`Drafting GitHub issue: ${topic}`, "info");
			pi.sendUserMessage(`Continue the /create-issue workflow.

Runtime context:
- Topic: ${topic}
- Draft path: ${draftPath}

First call skill({ name: "issue-logging" }) before continuing.`);
		},
	});

	// --- /pr-comments [number] ---
	pi.registerCommand("pr-comments", {
		description: "Synthesize review findings and post as PR comments",
		handler: async (args, ctx) => {
			const pr = await resolvePrNumber(pi, args?.trim(), ctx);
			if (!pr) return;

			unlocked.prComment = true;
			const scratchDir = getScratchDir(ctx.cwd);
			ctx.ui.notify(`PR comments workflow for #${pr.number}`, "info");
			pi.sendUserMessage(loadTemplate("pr-comments", { PR_NUMBER: pr.number, SCRATCH_DIR: scratchDir }));
		},
	});

	// --- /pr-walkthrough [number] [base] ---
	pi.registerCommand("pr-walkthrough", {
		description: "Interactive step-by-step PR walkthrough",
		handler: async (args, ctx) => {
			const parts = args?.trim().split(/\s+/) || [];
			const prArg = parts[0];
			const base = parts[1] || "main";

			const pr = await resolvePrNumber(pi, prArg, ctx);
			if (!pr) return;

			ctx.ui.notify(`Checking out PR #${pr.number} (${pr.branch})...`, "info");
			const checkout = await exec(pi, "gh", ["pr", "checkout", pr.number]);
			if (checkout.code !== 0) {
				ctx.ui.notify(`Failed to checkout PR: ${checkout.stderr}`, "error");
				return;
			}

			pi.sendUserMessage(loadTemplate("pr-walkthrough", { PR_NUMBER: pr.number, BRANCH: pr.branch, BASE: base }));
		},
	});
}
