import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerModeEditor } from "./editor.ts";
import { registerFooter } from "./footer.ts";
import { registerHeader } from "./header.ts";
import { registerTitle } from "./title.ts";

export default function (pi: ExtensionAPI): void {
	registerFooter(pi);
	registerHeader(pi);
	registerModeEditor(pi);
	registerTitle(pi);
}

// Public surface for other contexts (imported via #core/ui/index.ts only).
export { formatTitle } from "./title.ts";
