import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionAnalysis from "./src/companion/analysis.ts";
import registerCompanion from "./src/companion/index.ts";
import registerEngineering from "./src/engineering/index.ts";
import registerGit from "./src/git/index.ts";
import registerPanes from "./src/panes/index.ts";

// workspace + projects moved to pi-workspace.
// tasks + planning + agents moved to pi-tasks.
// session lifecycle/compaction/mode, capabilities, model-aliases, escalate moved to pi-core.
// footer/title/mode-editor moved to pi-ui.

export default function (pi: ExtensionAPI): void {
	registerEngineering(pi);
	registerCompanion(pi);
	registerCompanionAnalysis(pi);
	registerPanes(pi);
	registerGit(pi);
}
