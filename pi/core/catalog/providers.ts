/**
 * Capability catalog providers for Pi-native tools and skills.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isModelInvocationDisabled } from "../skills/skill-content.ts";
import { registerCatalogProvider } from "./index.ts";

export function registerCatalogProviders(pi: ExtensionAPI): void {
	registerCatalogProvider({
		id: "tools",
		list: () => {
			const activeNames = new Set(pi.getActiveTools());
			return pi
				.getAllTools()
				.filter((tool) => activeNames.has(tool.name))
				.map((tool) => ({
					type: "tools" as const,
					name: tool.name,
					description: tool.description,
				}));
		},
	});

	registerCatalogProvider({
		id: "skills",
		list: () =>
			pi
				.getCommands()
				.filter((command) => command.source === "skill")
				// Model-hidden skills (`disable-model-invocation`) are user-invoked only —
				// keep them out of the capability index the model sees.
				.filter((command) => !isModelInvocationDisabled(command.sourceInfo.path))
				.map((command) => ({
					type: "skills" as const,
					name: command.name.replace(/^skill:/, ""),
					description: command.description ?? "",
					path: command.sourceInfo.path,
				})),
	});
}
