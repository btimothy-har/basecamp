import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerContextInjection } from "./context-injection.ts";
import { registerProjectSession } from "./session.ts";

// Project resolution + nested-doc context injection. Registered by core so
// BASECAMP_PROJECT and project state are established before the ui banner and
// the workspace prompt read them. Prompt assembly stays in the workspace domain.
export default function registerProject(pi: ExtensionAPI): void {
	registerProjectSession(pi);
	registerContextInjection(pi);
}
