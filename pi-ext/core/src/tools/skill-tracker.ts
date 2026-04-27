/**
 * Skill invocation tracker lifecycle hooks.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { resetInvokedSkills } from "../../../platform/skill-tracker";

/** Register lifecycle handlers to reset skill state on session events. */
export function registerSkillLifecycle(pi: ExtensionAPI): void {
	pi.on("session_start", () => {
		resetInvokedSkills();
	});

	pi.on("session_compact", () => {
		resetInvokedSkills();
	});
}
