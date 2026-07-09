import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerContextInjection } from "./context-injection.ts";
import { registerHeader } from "./header.ts";
import { registerPrompt } from "./prompt.ts";
import { registerProjectSession } from "./session.ts";

export default function (pi: ExtensionAPI): void {
	registerProjectSession(pi);
	registerPrompt(pi);
	registerHeader(pi);
	registerContextInjection(pi);
}
