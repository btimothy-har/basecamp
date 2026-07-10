import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCommands } from "./pr.ts";

/** Git command surface (/create-pr). The worktree/repo mechanics under this module are imported directly. */
export function registerGit(pi: ExtensionAPI): void {
	registerCommands(pi);
}
