import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerContextInjection } from "./injection.ts";
import { registerProjectSession } from "./session.ts";
import { registerWorkspace } from "./workspace/index.ts";

/**
 * The active project's working environment. `registerCore` calls this after the core
 * registries: it wires the workspace runtime first (so the project-config `session_start`
 * can read workspace state), then resolves the project config, then the nested-context hook.
 */
export default function registerProject(pi: ExtensionAPI): void {
	registerWorkspace(pi);
	registerProjectSession(pi);
	registerContextInjection(pi);
}
