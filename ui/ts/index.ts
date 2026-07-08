import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerFooter } from "./footer.ts";
import { registerModeEditor } from "./mode-editor.ts";
import { registerTitle } from "./title.ts";

export default function (pi: ExtensionAPI): void {
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);
}
