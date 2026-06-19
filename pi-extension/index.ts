import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionAnalysis from "./src/companion/analysis.ts";
import registerCompanion from "./src/companion/index.ts";
import registerEngineering from "./src/engineering/index.ts";
import registerGit from "./src/git/index.ts";
import registerPanes from "./src/panes/index.ts";
import registerWorkflow from "./src/workflow/index.ts";

// workspace + projects have moved to pi-workspace.
// session lifecycle/compaction/mode, capabilities, model-aliases, escalate moved to pi-core.
// footer/title/mode-editor moved to pi-ui.

export default function (pi: ExtensionAPI): void {
	registerEngineering(pi);
	registerWorkflow(pi);
	registerCompanion(pi);
	registerCompanionAnalysis(pi);
	registerPanes(pi);
	registerGit(pi);
}
