/**
 * Workspace extension — shared workspace contract and future registrations.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerWorktreeCommand } from "./commands.ts";
import { registerWorkspaceGuards } from "./guards.ts";
import { registerWorkspaceRuntime } from "./service.ts";
import { registerWorkspaceSession } from "./session.ts";

export * from "#core/workspace/constants.ts";
export * from "#core/workspace/repo.ts";
export * from "#core/workspace/worktree.ts";
export * from "./commands.ts";
export * from "./guards.ts";
export * from "./service.ts";
export * from "./session.ts";
export * from "./unsafe-edit.ts";

export default function (pi: ExtensionAPI): void {
	const isSubagent = Number(process.env.BASECAMP_AGENT_DEPTH ?? "0") > 0;

	registerWorkspaceRuntime(pi);
	registerWorkspaceSession(pi);
	registerWorkspaceGuards(pi);

	// Primary-only interactions should not be available to subagents.
	if (!isSubagent) {
		registerWorktreeCommand(pi);
	}
}
