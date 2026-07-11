import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { setCompanionActive } from "#core/host/env.ts";
import registerPanes from "./panes/index.ts";
import registerCompanion from "./snapshot/index.ts";

export default function (pi: ExtensionAPI): void {
	setCompanionActive(false);
	registerCompanion(pi);
	registerPanes(pi);
}
