/**
 * Session UI — footer, title, mode-editor. Lifecycle/compaction/mode-command
 * have moved to pi-core; this module now only registers the UI layer.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerFooter } from "./ui/footer";
import { registerModeEditor } from "./ui/mode-editor";
import { registerTitle } from "./ui/title";

export default function (pi: ExtensionAPI) {
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);
}
