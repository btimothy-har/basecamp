import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import registerCapabilities from "./src/capabilities/index.ts";
import { registerEscalate } from "./src/escalate/tool.ts";
import registerModelAliases from "./src/model-aliases/index.ts";
import { isSubagent, setBasecampEnv } from "./src/platform/env.ts";
import { registerCwdProvider } from "./src/platform/exec.ts";
import { registerModeShortcut } from "./src/session/commands/mode.ts";
import { registerCompactionModel } from "./src/session/runtime/compaction.ts";
import { registerSession } from "./src/session/runtime/session.ts";
import { registerState } from "./src/state/index.ts";
import { resolveGitInfo } from "./src/workspace/repo.ts";

export default function (pi: ExtensionAPI): void {
	// Default cwd provider — pi-workspace overrides this when installed.
	registerCwdProvider(() => process.cwd());

	// Core registries + lifecycle
	registerState(pi);
	registerSession(pi);
	registerCompactionModel(pi);
	registerCapabilities(pi);
	registerModelAliases(pi);

	// Default git detection at session_start — pi-workspace overrides with full config.
	pi.on("session_start", async () => {
		const gitInfo = await resolveGitInfo(pi, process.cwd());
		setBasecampEnv("BASECAMP_REPO", gitInfo.repoName);
	});

	// Primary-only interactions
	if (!isSubagent()) {
		registerModeShortcut(pi);
		registerEscalate(pi);
	}
}
