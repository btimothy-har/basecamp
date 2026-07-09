import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerFooter } from "./footer.ts";
import { registerModeEditor } from "./mode-editor.ts";
import { registerTitle } from "./title.ts";

export default function (pi: ExtensionAPI): void {
	registerFooter(pi);
	registerModeEditor(pi);
	registerTitle(pi);
}

// Public surface for other contexts (imported via #ui/index.ts only).
export { buildTitleContext, formatTitle } from "./title.ts";
