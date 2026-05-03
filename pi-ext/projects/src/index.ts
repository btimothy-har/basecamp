import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerContextInjection } from "./context-injection.ts";
import { registerHeader } from "./header.ts";
import { registerPrompt } from "./prompt.ts";
import { registerProjectSession } from "./session.ts";

export * from "./config.ts";
export * from "./header.ts";
export * from "./project.ts";
export * from "./prompt.ts";
export * from "./session.ts";

export default function (pi: ExtensionAPI): void {
	registerProjectSession(pi);
	registerPrompt(pi);
	registerHeader(pi);
	registerContextInjection(pi);
}
