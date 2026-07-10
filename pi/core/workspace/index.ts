import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "../host/env.ts";
import { registerWorktreeCommand } from "./command.ts";
import { registerWorkspaceGuards } from "./guards.ts";
import { registerWorkspaceRuntime } from "./runtime.ts";
import { registerWorkspaceSession } from "./session.ts";

/**
 * Workspace runtime — worktree state machine, session bootstrap, edit guards, and
 * the `/worktree` command. Registered by `registerCore` (before project + ui), since
 * project's session_start reads workspace state and the ui banner renders it.
 */
export function registerWorkspace(pi: ExtensionAPI): void {
	registerWorkspaceRuntime(pi);
	registerWorkspaceSession(pi);
	registerWorkspaceGuards(pi);
	if (!isSubagent()) {
		registerWorktreeCommand(pi);
	}
}
