/**
 * Workspace extension — shared workspace contract and future registrations.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export * from "./constants";
export * from "./repo";
export * from "./worktree";

export default function (pi: ExtensionAPI): void {
	void pi;
}
