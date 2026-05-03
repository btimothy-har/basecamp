/**
 * Capabilities extension — skill tool, skill lifecycle, and catalog providers.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerCapabilityCatalogProviders } from "./catalog-providers";
import { registerSkillTool } from "./skill";
import { registerSkillLifecycle } from "./skill-tracker";

export default function (pi: ExtensionAPI) {
	registerSkillLifecycle(pi);
	registerCapabilityCatalogProviders(pi);
	registerSkillTool(pi);
}
