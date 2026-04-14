/**
 * Git Protect — guards against destructive git and gh operations.
 *
 * Block rules: gate regex scopes to a command, test regex triggers the block.
 * gh commands are blocked by default with an allow-list of safe operations.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

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

export function registerGitProtect(pi: ExtensionAPI): void {
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return;

		const cmd = event.input.command;
		if (!cmd) return;

		// Check block rules
		for (const rule of BLOCK_RULES) {
			if (rule.gate.test(cmd) && rule.test.test(cmd)) {
				return { block: true, reason: rule.reason };
			}
		}

		// gh: block by default, allow-list overrides
		if (/^gh\s+/.test(cmd) && !GH_ALLOW.some((r) => r.test(cmd))) {
			return { block: true, reason: "This gh command is blocked — only read-only gh operations are allowed. Ask the user to run this command themselves if needed." };
		}
	});
}
