import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { setCompanionActive } from "#core/platform/env.ts";
import registerCompanionAnalysis from "./analysis.ts";
import registerCompanion from "./companion-index.ts";
import registerPanes from "./panes-index.ts";

export default function (pi: ExtensionAPI): void {
	setCompanionActive(false);
	registerCompanion(pi);
	registerPanes(pi);
	registerCompanionAnalysis(pi);
}
