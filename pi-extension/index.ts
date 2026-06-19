import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import registerCompanionAnalysis from "./src/companion/analysis.ts";
import registerCompanion from "./src/companion/index.ts";
import registerPanes from "./src/panes/index.ts";

// engineering moved to pi-engineering.

export default function (pi: ExtensionAPI): void {
	registerCompanion(pi);
}
