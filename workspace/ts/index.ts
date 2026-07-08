import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSubagent } from "pi-core/platform/env.ts";
import registerProjects from "./src/projects/index.ts";
import { registerWorktreeCommand } from "./src/workspace/commands.ts";
import { registerWorkspaceGuards } from "./src/workspace/guards.ts";
import { registerWorkspaceRuntime } from "./src/workspace/service.ts";
import { registerWorkspaceSession } from "./src/workspace/session.ts";

export default function (pi: ExtensionAPI): void {
	registerWorkspaceRuntime(pi);
	registerWorkspaceSession(pi);
	registerWorkspaceGuards(pi);
	registerProjects(pi);

	if (!isSubagent()) {
		registerWorktreeCommand(pi);
	}
}
