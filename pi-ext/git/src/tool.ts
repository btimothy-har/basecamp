/**
 * pr_publish tool — lets the LLM submit a PR description for user review
 * via pi's inline editor, then publishes to GitHub.
 *
 * Gated behind /pull-request: only works when activePR is set.
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { activePR } from "./guards";
import { getScratchDir } from "./utils";

export function registerTool(pi: ExtensionAPI): void {
	pi.registerTool({
		name: "pr_publish",
		label: "Publish PR",
		description:
			"Submit a PR title and description for user review in an inline editor, then publish to GitHub. " +
			"Only available after /pull-request has been invoked.",
		promptSnippet: "Open inline editor for PR description review, then publish to GitHub",
		parameters: Type.Object({
			title: Type.String({ description: "PR title. Imperative mood, <70 chars." }),
			body: Type.String({ description: "PR description body in markdown." }),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			if (!activePR) {
				throw new Error("No active PR workflow. Run /pull-request first.");
			}

			const { number: prNumber } = activePR;

			// Open inline editor with title on line 1, blank line, then body
			const prefill = `${params.title}\n\n${params.body}`;
			const edited = await ctx.ui.editor(`PR #${prNumber} — Review & Edit`, prefill);

			if (edited == null) {
				return {
					content: [{ type: "text", text: "User cancelled the editor. Ask what they'd like to change." }],
					details: null,
				};
			}

			// Split: first line = title, rest = body
			const lines = edited.split("\n");
			const title = lines[0]?.trim() || params.title;
			const body = lines.slice(1).join("\n").trim();

			// Persist to scratch dir
			const scratchDir = getScratchDir(ctx.cwd);
			const prDir = path.join(scratchDir, "pull-requests");
			fs.mkdirSync(prDir, { recursive: true });
			const filePath = path.join(prDir, `${prNumber}.md`);
			fs.writeFileSync(filePath, `${title}\n\n${body}\n`, "utf-8");

			// Publish to GitHub
			const result = await pi.exec("gh", ["pr", "edit", prNumber, "--title", title, "--body", body]);

			if (result.code !== 0) {
				throw new Error(`Failed to update PR #${prNumber}: ${result.stderr}\nDescription saved to ${filePath}`);
			}

			const urlResult = await pi.exec("gh", ["pr", "view", prNumber, "--json", "url", "-q", ".url"]);
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
