/**
 * Capabilities extension — skill tool, skill lifecycle, and catalog providers.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerCapabilityCatalogProviders } from "./catalog-providers.ts";
import { registerSkillTool } from "./skill.ts";
import { registerSkillLifecycle } from "./skill-tracker.ts";

export default function (pi: ExtensionAPI) {
	registerSkillLifecycle(pi);
	registerCapabilityCatalogProviders(pi);
	registerSkillTool(pi);
}
