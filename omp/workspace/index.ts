/** Workspace reminders for all OMP launches. */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerWorkspaceGuidance from "./guidance.ts";
import registerStartupWarning from "./startup.ts";

export default function registerWorkspace(pi: ExtensionAPI): void {
	registerStartupWarning(pi);
	registerWorkspaceGuidance(pi);
}
