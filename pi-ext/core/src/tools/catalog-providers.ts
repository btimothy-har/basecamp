/**
 * Core catalog providers for Pi-native tools and skills.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerCatalogProvider } from "../../../platform/catalog";

export function registerCoreCatalogProviders(pi: ExtensionAPI): void {
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
				.map((command) => ({
					type: "skills" as const,
					name: command.name.replace(/^skill:/, ""),
					description: command.description ?? "",
					path: command.sourceInfo.path,
				})),
	});
}
