import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerModeShortcut } from "./agent-mode/command.ts";
import registerCapabilities from "./capabilities/index.ts";
import { registerEscalate } from "./escalate/tool.ts";
import registerModelAliases from "./model-aliases/index.ts";
import { isSubagent, setBasecampEnv } from "./platform/env.ts";
import { registerCwdProvider } from "./platform/exec.ts";
import { registerCompactionModel } from "./session/runtime/compaction.ts";
import { registerSession } from "./session/runtime/session.ts";
import { registerState } from "./session/state/index.ts";
import registerUi from "./ui/index.ts";
import { resolveGitInfo } from "./workspace/repo.ts";

export default function (pi: ExtensionAPI): void {
	// Default cwd provider — the workspace module overrides this during registration.
	registerCwdProvider(() => process.cwd());

	// Core registries + lifecycle
	registerState(pi);
	registerSession(pi);
	registerCompactionModel(pi);
	registerCapabilities(pi);
	registerModelAliases(pi);

	// Default git detection at session_start — the workspace module overrides with full config.
	pi.on("session_start", async () => {
		const gitInfo = await resolveGitInfo(pi, process.cwd());
		setBasecampEnv("BASECAMP_REPO", gitInfo.repoName);
	});

	// Primary-only interactions
	if (!isSubagent()) {
		registerModeShortcut(pi);
		registerEscalate(pi);
	}

	// Framework UI (footer/header/title/mode) — a core submodule like capabilities
	// and escalate. Registered last so its render + session_start hooks observe
	// the state core's own registries have already wired.
	registerUi(pi);
}
