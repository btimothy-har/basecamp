/**
 * Workspace extension — shared workspace contract and future registrations.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerWorktreeCommand } from "./commands.ts";
import { registerWorkspaceGuards } from "./guards.ts";
import { registerWorkspaceRuntime } from "./service.ts";

export * from "./commands.ts";
export * from "./constants.ts";
export * from "./guards.ts";
export * from "./repo.ts";
export * from "./service.ts";
export * from "./unsafe-edit.ts";
export * from "./worktree.ts";

export default function (pi: ExtensionAPI): void {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerWorkspaceRuntime(pi);
	registerWorkspaceGuards(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerWorktreeCommand(pi);
	}
}
