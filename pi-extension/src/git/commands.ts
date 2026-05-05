/**
 * Git commands — PR, issue, and git workflow commands.
 *
 *   /create-pr [context]                      — create/find draft PR, review, describe, publish
 *   /create-issue [topic]                     — draft and publish a GitHub issue through review
 *   /pr-comments [number]                     — synthesize review findings, post as PR comments
 *   /code-walkthrough [pr|branch] [base]      — context-first code walkthrough
 */

import * as crypto from "node:crypto";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { exec } from "../platform/exec";
import { activateWorkspaceWorktree, attachWorkspaceWorktreePath } from "../platform/workspace";
import { activeIssueDraft, setActiveIssueDraft, setActivePR, unlocked } from "./guards";
import { createIssueDraftPath, getScratchDir, loadTemplate, resolvePrNumber } from "./utils";

type PushResult = "pushed" | "up-to-date" | "cancelled" | "diverged" | "failed";

type WalkthroughTargetKind = "pr" | "branch";

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function isPrNumberTarget(target: string): boolean {
	return /^\d+$/.test(target);
}

function reviewWorktreeLabel(kind: WalkthroughTargetKind, target: string): string {
	if (kind === "pr") return `review-pr-${target}`;

	const slug =
		target
			.replace(/[^A-Za-z0-9._-]+/g, "-")
			.replace(/^[^A-Za-z0-9]+/, "")
			.slice(0, 40) || "branch";
	const hash = crypto.createHash("sha1").update(target).digest("hex").slice(0, 8);
	return `review-branch-${slug}-${hash}`;
}

async function activateReviewWorktree(label: string, ctx: any): Promise<string | null> {
	try {
		const worktree = await activateWorkspaceWorktree(label);
		ctx.ui.notify(`Review worktree active: ${worktree.label}`, "info");
		return worktree.path;
	} catch (error) {
		ctx.ui.notify(`Failed to activate review worktree: ${errorMessage(error)}`, "error");
		return null;
	}
}

async function refreshReviewWorktree(worktreePath: string, ctx: any): Promise<boolean> {
	try {
		const worktree = await attachWorkspaceWorktreePath(worktreePath);
		ctx.ui.notify(`Review worktree checkout: ${worktree.branch ?? "detached"}`, "info");
		return true;
	} catch (error) {
		ctx.ui.notify(`Failed to refresh review worktree state: ${errorMessage(error)}`, "error");
		return false;
	}
}

async function validateBranchForReview(pi: ExtensionAPI, branchName: string, ctx: any): Promise<boolean> {
	const valid = await exec(pi, "git", ["check-ref-format", "--branch", branchName]);
	if (valid.code !== 0) {
		ctx.ui.notify(`Invalid branch name: ${branchName}`, "error");
		return false;
	}
	return true;
}

async function checkoutBranchForReview(pi: ExtensionAPI, branchName: string, ctx: any): Promise<boolean> {
	const fetch = await exec(pi, "git", ["fetch", "origin"], { timeout: 30_000 });
	if (fetch.code !== 0) {
		ctx.ui.notify(`Fetch from origin failed; trying local branch ${branchName}`, "info");
	}

	const checkout = await exec(pi, "git", ["checkout", branchName]);
	if (checkout.code !== 0) {
		ctx.ui.notify(`Failed to checkout branch ${branchName} in review worktree: ${checkout.stderr}`, "error");
		return false;
	}
	return true;
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
	// --- /create-pr [context] ---
	pi.registerCommand("create-pr", {
		description: "Create, review, and publish a pull request",
		handler: async (args, ctx) => {
			const reviewContext = args?.trim() || "";
			const baseInput = (await ctx.ui.input("Base branch", "main"))?.trim();
			const base = baseInput || "main";

			const branch = await exec(pi, "git", ["branch", "--show-current"]);
			const branchName = branch.stdout.trim();
			if (!branchName) {
				ctx.ui.notify("Not on a branch — cannot create PR", "error");
				return;
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
			const reviewContextBlock = reviewContext ? `\n\nAdditional context:\n${reviewContext}` : "";
			pi.sendUserMessage(`Please prepare this pull request for my review.

Context:
- PR: #${prNumber}
- Base branch: ${base}
- Current branch: ${branchName}${reviewContextBlock}

Start by calling skill({ name: "pull-request" }), then review the changes, draft the PR title/body, and submit it with publish_pr.`);
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
			pi.sendUserMessage(`Please draft this GitHub issue for my review.

Context:
- Topic: ${topic}
- Draft path: ${draftPath}

Start by calling skill({ name: "issue-logging" }), then investigate as needed, write the issue draft to the provided path, and submit it with publish_issue.`);
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

	async function startCodeWalkthrough(args: string | undefined, ctx: any): Promise<void> {
		const parts = args?.trim().split(/\s+/).filter(Boolean) || [];
		const targetArg = parts[0];
		const base = parts[1] || "main";

		if (targetArg && isPrNumberTarget(targetArg)) {
			const pr = await resolvePrNumber(pi, targetArg, ctx);
			if (!pr) return;

			const worktreePath = await activateReviewWorktree(reviewWorktreeLabel("pr", pr.number), ctx);
			if (!worktreePath) return;

			ctx.ui.notify(`Checking out PR #${pr.number} (${pr.branch}) in review worktree...`, "info");
			const checkout = await exec(pi, "gh", ["pr", "checkout", pr.number]);
			if (checkout.code !== 0) {
				ctx.ui.notify(`Failed to checkout PR in review worktree: ${checkout.stderr}`, "error");
				return;
			}
			if (!(await refreshReviewWorktree(worktreePath, ctx))) return;

			pi.sendUserMessage(
				loadTemplate("pr-walkthrough", {
					TARGET_LABEL: `PR #${pr.number}`,
					TARGET_JSON: JSON.stringify({ kind: "pr", prNumber: Number(pr.number), branch: pr.branch, base }, null, 2),
					TARGET_CONTEXT_COMMANDS: `gh pr view ${pr.number} --json number,title,body,state,author,headRefName,headRefOid,baseRefName,labels,assignees,reviewRequests,closingIssuesReferences,commits`,
					BRANCH: pr.branch,
					BASE: base,
				}),
			);
			return;
		}

		if (targetArg) {
			const branchName = targetArg;
			if (!(await validateBranchForReview(pi, branchName, ctx))) return;

			const worktreePath = await activateReviewWorktree(reviewWorktreeLabel("branch", branchName), ctx);
			if (!worktreePath) return;
			if (!(await checkoutBranchForReview(pi, branchName, ctx))) return;
			if (!(await refreshReviewWorktree(worktreePath, ctx))) return;

			ctx.ui.notify(`Code walkthrough workflow for branch ${branchName} against ${base}`, "info");
			pi.sendUserMessage(
				loadTemplate("pr-walkthrough", {
					TARGET_LABEL: `branch ${branchName}`,
					TARGET_JSON: JSON.stringify({ kind: "branch", branch: branchName, base }, null, 2),
					TARGET_CONTEXT_COMMANDS: `gh pr list --head ${branchName} --json number,title,body,state,author,headRefName,headRefOid,baseRefName,labels,assignees,reviewRequests,closingIssuesReferences,commits`,
					BRANCH: branchName,
					BASE: base,
				}),
			);
			return;
		}

		const branch = await exec(pi, "git", ["branch", "--show-current"]);
		const branchName = branch.stdout.trim();
		if (!branchName) {
			ctx.ui.notify("Not on a branch — pass a PR number or branch name to review in a worktree", "error");
			return;
		}

		ctx.ui.notify(`Code walkthrough workflow for branch ${branchName} against ${base}`, "info");
		pi.sendUserMessage(
			loadTemplate("pr-walkthrough", {
				TARGET_LABEL: `branch ${branchName}`,
				TARGET_JSON: JSON.stringify({ kind: "branch", branch: branchName, base }, null, 2),
				TARGET_CONTEXT_COMMANDS: `gh pr list --head ${branchName} --json number,title,body,state,author,headRefName,headRefOid,baseRefName,labels,assignees,reviewRequests,closingIssuesReferences,commits`,
				BRANCH: branchName,
				BASE: base,
			}),
		);
	}

	// --- /code-walkthrough [pr|branch] [base] ---
	pi.registerCommand("code-walkthrough", {
		description: "Context-first code walkthrough for a PR number, branch, or current branch",
		handler: startCodeWalkthrough,
	});
}
