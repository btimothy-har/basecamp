/**
 * pr_publish tool — lets the LLM submit a PR description for user review
 * via a read-only overlay with feedback support, then publishes to GitHub.
 *
 * Gated behind /pull-request: only works when activePR is set.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { exec } from "../../core/src/runtime/session";
import { activePR } from "./guards";
import { showPrReview } from "./review";
import { getScratchDir } from "./utils";

export function registerTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "pr_publish",
		label: "Publish PR",
		description:
			"Submit a PR title and description for user review. User can approve to publish, " +
			"or provide feedback for revision. Only available after /pull-request has been invoked.",
		promptSnippet: "Show PR description for review — user can publish or give feedback for revision",
		parameters: Type.Object({
			title: Type.String({ description: "PR title. Imperative mood, <70 chars." }),
			body: Type.String({ description: "PR description body in markdown." }),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (!activePR) {
				throw new Error("No active PR workflow. Run /pull-request first.");
			}

			const { number: prNumber } = activePR;

			const result = await showPrReview(prNumber, params.title, params.body, ctx);

			if (result.action === "cancel") {
				return {
					content: [{ type: "text", text: "User cancelled. Ask what they'd like to change." }],
					details: null,
				};
			}

			if (result.action === "feedback") {
				return {
					content: [
						{
							type: "text",
							text: `User feedback on PR description:\n\n${result.text}\n\nRevise the PR description based on this feedback and call pr_publish again.`,
						},
					],
					details: null,
				};
			}

			const title = params.title;
			const body = params.body;

			// Persist to scratch dir
			const scratchDir = getScratchDir(ctx.cwd);
			const prDir = path.join(scratchDir, "pull-requests");
			fs.mkdirSync(prDir, { recursive: true });
			const filePath = path.join(prDir, `${prNumber}.md`);
			fs.writeFileSync(filePath, `${title}\n\n${body}\n`, "utf-8");

			const ghResult = await exec(pi, "gh", ["pr", "edit", prNumber, "--title", title, "--body", body]);

			if (ghResult.code !== 0) {
				throw new Error(`Failed to update PR #${prNumber}: ${ghResult.stderr}\nDescription saved to ${filePath}`);
			}

			const urlResult = await exec(pi, "gh", ["pr", "view", prNumber, "--json", "url", "-q", ".url"]);
			const url = urlResult.stdout.trim();

			return {
				content: [
					{
						type: "text",
						text: `PR #${prNumber} updated.\nURL: ${url}\nDescription saved to ${filePath}`,
					},
				],
				details: null,
			};
		},
	});
}
