import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerModeShortcut } from "./agent-mode/toggle.ts";
import { registerCatalogProviders } from "./catalog/providers.ts";
import { registerEscalate } from "./escalate/tool.ts";
import { isSubagent, setBasecampEnv } from "./host/env.ts";
import { registerCwdProvider } from "./host/exec.ts";
import registerModelAliases from "./model/index.ts";
import registerProject from "./project/index.ts";
import { registerCompactionModel } from "./session/runtime/compaction.ts";
import { registerSession } from "./session/runtime/session.ts";
import { registerState } from "./session/state/index.ts";
import registerSkills from "./skills/index.ts";
import registerUi from "./ui/index.ts";
import { registerWorkspace } from "./workspace/index.ts";
import { resolveGitInfo } from "./workspace/repo.ts";

export default function (pi: ExtensionAPI): void {
	// Default cwd provider — the workspace module overrides this during registration.
	registerCwdProvider(() => process.cwd());

	// Core registries + lifecycle
	registerState(pi);
	registerSession(pi);
	registerCompactionModel(pi);
	registerSkills(pi);
	registerCatalogProviders(pi);
	registerModelAliases(pi);

	// Default git detection at session_start — the workspace module overrides with full config.
	pi.on("session_start", async () => {
		const gitInfo = await resolveGitInfo(pi, process.cwd());
		setBasecampEnv("BASECAMP_REPO", gitInfo.repoName);
	});

	// Workspace runtime + project resolution — project's session_start reads workspace
	// state, so it registers right after workspace (both core-owned, ordered here).
	registerWorkspace(pi);
	registerProject(pi);

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
