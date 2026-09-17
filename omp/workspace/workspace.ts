/**
 * Standalone workspace extension entrypoint. The root package lists it beside
 * its main entrypoint, while the installer's ambient manifest can load it
 * independently for plain OMP launches.
 */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import registerWorkspace from "./index.ts";

export default function registerWorkspaceExtension(pi: ExtensionAPI): void {
	registerWorkspace(pi);
}
