import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/host/env.ts";
import registerProject from "#core/project/index.ts";
import { registerWorkspaceGuards } from "./guards/index.ts";
import { registerPrompt } from "./prompt/prompt.ts";
import { registerWorktreeCommand } from "./worktree/command.ts";
import { registerWorkspaceRuntime } from "./worktree/service.ts";
import { registerWorkspaceSession } from "./worktree/session.ts";

export default function (pi: ExtensionAPI): void {
	registerWorkspaceRuntime(pi);
	registerWorkspaceSession(pi);
	registerWorkspaceGuards(pi);
	// Project code is core-owned but registered here: its session_start hook
	// requires workspace runtime state, so it must fire after workspace setup.
	registerProject(pi);
	registerPrompt(pi);

	if (!isSubagent()) {
		registerWorktreeCommand(pi);
	}
}
