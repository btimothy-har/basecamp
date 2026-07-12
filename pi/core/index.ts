import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerModeShortcut } from "./agent-mode/toggle.ts";
import { registerCatalogProviders } from "./catalog/providers.ts";
import { registerEscalate } from "./escalate/tool.ts";
import { registerGit } from "./git/index.ts";
import { isSubagent } from "./host/env.ts";
import { registerHubConnection } from "./hub/index.ts";
import registerModelAliases from "./model/index.ts";
import registerProject from "./project/index.ts";
import { registerCompactionModel } from "./session/runtime/compaction.ts";
import { registerSession } from "./session/runtime/session.ts";
import { registerState } from "./session/state/index.ts";
import registerSkills from "./skills/index.ts";
import registerSwarm from "./swarm/index.ts";
import registerUi from "./ui/index.ts";

export default function (pi: ExtensionAPI): void {
	// Core registries + lifecycle
	registerState(pi);
	registerSession(pi);
	registerCompactionModel(pi);
	registerSkills(pi);
	registerCatalogProviders(pi);
	registerModelAliases(pi);

	// The active project: workspace runtime + config resolution + context injection
	// (registerProject sequences them), then the git command surface.
	registerProject(pi);
	registerGit(pi);

	// The hub-daemon connector (adapter): connects at session_start for top-level
	// sessions and daemon-spawned agents. Consumers ride on it.
	registerHubConnection(pi);

	// The agent-dispatch primitive (adapter over the hub connection): the agent
	// catalog + session surfaces (dispatch/ask/cancel/peer tools, reporter,
	// widget). Runs for top-level sessions and daemon-spawned agents alike; the
	// code-review and workstream feature domains consume it via #core/swarm.
	registerSwarm(pi);

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
