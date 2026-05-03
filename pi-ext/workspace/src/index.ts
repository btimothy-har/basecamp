/**
 * Workspace extension — shared workspace contract and future registrations.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerWorkspaceRuntime } from "./service.ts";

export * from "./constants.ts";
export * from "./repo.ts";
export * from "./service.ts";
export * from "./unsafe-edit.ts";
export * from "./worktree.ts";

export default function (pi: ExtensionAPI): void {
	registerWorkspaceRuntime(pi);
}
