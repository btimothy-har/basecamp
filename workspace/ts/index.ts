import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "#core/platform/env.ts";
import registerProjects from "./projects/index.ts";
import { registerWorktreeCommand } from "./workspace/commands.ts";
import { registerWorkspaceGuards } from "./workspace/guards.ts";
import { registerWorkspaceRuntime } from "./workspace/service.ts";
import { registerWorkspaceSession } from "./workspace/session.ts";

export default function (pi: ExtensionAPI): void {
	registerWorkspaceRuntime(pi);
	registerWorkspaceSession(pi);
	registerWorkspaceGuards(pi);
	registerProjects(pi);

	if (!isSubagent()) {
		registerWorktreeCommand(pi);
	}
}
