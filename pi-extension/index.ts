import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionAnalysis from "./src/companion/analysis.ts";
import registerCompanion from "./src/companion/index.ts";
import registerEngineering from "./src/engineering/index.ts";
import registerPanes from "./src/panes/index.ts";

// git moved to pi-git.
// workspace+projects moved to pi-workspace.
// tasks+planning+agents moved to pi-tasks.

export default function (pi: ExtensionAPI): void {
	registerEngineering(pi);
	registerCompanion(pi);
}
