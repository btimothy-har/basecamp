import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerFooter } from "./src/footer.ts";
import { registerModeEditor } from "./src/mode-editor.ts";
import { registerTitle } from "./src/title.ts";

export default function (pi: ExtensionAPI): void {
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);
}
