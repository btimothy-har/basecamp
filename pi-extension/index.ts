import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionAnalysis from "./src/companion/analysis.ts";
import registerCompanion from "./src/companion/index.ts";
import registerEngineering from "./src/engineering/index.ts";
import registerGit from "./src/git/index.ts";
import registerPanes from "./src/panes/index.ts";
import registerProjects from "./src/projects/index.ts";
import registerSession from "./src/session/index.ts";
import registerWorkflow from "./src/workflow/index.ts";
import registerWorkspace from "./src/workspace/index.ts";

// state, session (lifecycle/compaction/mode), capabilities (skill tool),
// model-aliases, and escalate have moved to pi-core.
// session/index.ts here now only registers footer/title/mode-editor (pi-ui bound).

export default function (pi: ExtensionAPI): void {
	registerWorkspace(pi);
	registerSession(pi);
	registerEngineering(pi);
	registerProjects(pi);
	registerWorkflow(pi);
	registerCompanion(pi);
	registerCompanionAnalysis(pi);
	registerPanes(pi);
	registerGit(pi);
}
