import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerContextInjection } from "./context-injection.ts";
import { registerProjectSession } from "./session.ts";

// Project resolution + nested-doc context injection. Registered by the workspace
// domain (not core): its session_start reads workspace runtime state, so it must
// run after workspace init, and pi fires session_start in registration order.
export default function registerProject(pi: ExtensionAPI): void {
	registerProjectSession(pi);
	registerContextInjection(pi);
}
