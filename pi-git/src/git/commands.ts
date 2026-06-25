/**
 * Git commands — PR prompt and code walkthrough commands.
 *
 *   /create-pr [context]                      — prompt the agent to create/update a PR via bash/gh
 *   /code-walkthrough [pr|branch] [base]      — context-first code walkthrough
 */

import * as crypto from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exec } from "pi-core/platform/exec.ts";
import { activateWorkspaceWorktree, attachWorkspaceWorktreePath } from "pi-core/platform/workspace.ts";
import { loadTemplate, resolvePrNumber } from "./utils";

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

function createPrPrompt(base: string, context: string): string {
	const contextBlock = context ? `\n\nAdditional context from the user:\n${context}` : "";
	return `Please create or update the pull request directly using bash commands.

Context:
- Base branch: ${base}${contextBlock}

Instructions:
1. Inspect the current branch and working tree state.
2. Check whether a PR already exists for the current branch with \`gh pr list --head <branch>\` or \`gh pr view\`.
3. Push the branch if needed, setting the upstream when necessary.
4. If a PR already exists, update it with \`gh pr edit\` as needed. Otherwise create a draft PR against ${base} with \`gh pr create --draft --base ${base}\`.
5. Write a clear PR title and body based on the diff and the context above.
6. Summarize the result for me, including the PR number/URL and whether the branch was pushed.`;
}

export function registerCommands(pi: ExtensionAPI): void {
	// --- /create-pr [context] ---
	pi.registerCommand("create-pr", {
		description: "Prompt the agent to create or update a pull request via bash/gh",
		handler: async (args, ctx) => {
			const reviewContext = args?.trim() || "";
			const baseInput = ctx.hasUI ? (await ctx.ui.input("Base branch", "main"))?.trim() : undefined;
			const base = baseInput || "main";
			pi.sendUserMessage(createPrPrompt(base, reviewContext));
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
