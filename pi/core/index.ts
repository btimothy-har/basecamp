import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerModeShortcut } from "./agent-mode/toggle.ts";
import { registerCatalogProviders } from "./catalog/providers.ts";
import { registerEscalate } from "./escalate/tool.ts";
import { registerGit } from "./git/index.ts";
import { isSubagent } from "./host/env.ts";
import registerModelAliases from "./model/index.ts";
import registerProject from "./project/index.ts";
import { registerCompactionModel } from "./session/runtime/compaction.ts";
import { registerSession } from "./session/runtime/session.ts";
import { registerState } from "./session/state/index.ts";
import registerSkills from "./skills/index.ts";
import registerUi from "./ui/index.ts";
import { registerWorkspace } from "./workspace/index.ts";

export default function (pi: ExtensionAPI): void {
	// Core registries + lifecycle
	registerState(pi);
	registerSession(pi);
	registerCompactionModel(pi);
	registerSkills(pi);
	registerCatalogProviders(pi);
	registerModelAliases(pi);

	// Workspace runtime (registers the real cwd provider + BASECAMP_* env at session_start),
	// then project resolution — project's session_start reads workspace state, so it comes after.
	registerWorkspace(pi);
	registerProject(pi);
	registerGit(pi);

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
