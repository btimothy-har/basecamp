import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { setCompanionActive } from "pi-core/platform/env.ts";
import registerCompanion from "./src/companion-index.ts";
import registerPanes from "./src/panes-index.ts";

export default function (pi: ExtensionAPI): void {
	setCompanionActive(true);
	registerCompanion(pi);
	registerPanes(pi);
}
