/**
 * Git commands — PR prompt command.
 *
 *   /create-pr [context] — prompt the agent to create/update a PR via bash/gh
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exec } from "#core/platform/exec.ts";

async function resolveDefaultBase(pi: ExtensionAPI): Promise<string> {
	const head = await exec(pi, "git", ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]);
	const ref = head.stdout.trim();
	return ref.startsWith("origin/") ? ref.slice("origin/".length) : "main";
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
	pi.registerCommand("create-pr", {
		description: "Prompt the agent to create or update a pull request via bash/gh",
		handler: async (args, ctx) => {
			const reviewContext = args?.trim() || "";
			const fallback = await resolveDefaultBase(pi);
			const baseInput = ctx.hasUI ? (await ctx.ui.input("Base branch", fallback))?.trim() : undefined;
			const base = baseInput || fallback;
			pi.sendUserMessage(createPrPrompt(base, reviewContext));
		},
	});
}
