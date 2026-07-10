/**
 * Skills extension — the skill() tool and its session lifecycle.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerSkillTool } from "./skill.ts";
import { registerSkillLifecycle } from "./tracker.ts";

export default function (pi: ExtensionAPI) {
	registerSkillLifecycle(pi);
	registerSkillTool(pi);
}
