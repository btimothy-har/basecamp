/**
 * Git commands — PR workflow commands.
 *
 *   /pull-request [base]          — create/find draft PR, review, describe, publish
 *   /pr-comments [number]         — synthesize review findings, post as PR comments
 *   /pr-walkthrough [number] [base] — interactive step-by-step walkthrough
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { setActivePR, unlocked } from "./guards";
import { getScratchDir, loadTemplate, resolvePrNumber } from "./utils";

export function registerCommands(pi: ExtensionAPI): void {
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

			const existing = await pi.exec("gh", ["pr", "list", "--head", branchName, "--json", "number,url", "-q", ".[0]"]);

			let prNumber: string;

			if (existing.stdout.trim()) {
				const pr = JSON.parse(existing.stdout.trim());
				prNumber = String(pr.number);
				ctx.ui.notify(`Found existing PR #${prNumber}`, "info");

				const ahead = await pi.exec("git", ["rev-list", "--count", "@{u}..HEAD"]);
				if (ahead.code === 0 && parseInt(ahead.stdout.trim(), 10) > 0) {
					ctx.ui.notify("Pushing local commits...", "info");
					const push = await pi.exec("git", ["push"]);
					if (push.code !== 0) {
						ctx.ui.notify(`Failed to push: ${push.stderr}`, "error");
						return;
					}
				}
			} else {
				const upstream = await pi.exec("git", ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]);
				if (upstream.code !== 0) {
					ctx.ui.notify(`Pushing ${branchName} to origin...`, "info");
					const push = await pi.exec("git", ["push", "-u", "origin", branchName]);
					if (push.code !== 0) {
						ctx.ui.notify(`Failed to push: ${push.stderr}`, "error");
						return;
					}
				}

				ctx.ui.notify(`Creating draft PR against ${base}...`, "info");
				const create = await pi.exec("gh", [
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
			pi.sendUserMessage(loadTemplate("pull-request", { PR_NUMBER: prNumber, BASE: base }));
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
			const checkout = await pi.exec("gh", ["pr", "checkout", pr.number]);
			if (checkout.code !== 0) {
				ctx.ui.notify(`Failed to checkout PR: ${checkout.stderr}`, "error");
				return;
			}

			pi.sendUserMessage(loadTemplate("pr-walkthrough", { PR_NUMBER: pr.number, BRANCH: pr.branch, BASE: base }));
		},
	});
}
