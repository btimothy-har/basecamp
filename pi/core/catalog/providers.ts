/**
 * Capability catalog provider for Pi-native skills.
 *
 * There is deliberately no tools provider: tool contracts reach the model
 * through the API tools array, so the prompt never lists them.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isModelInvocationDisabled } from "#core/skills/skill-content.ts";
import { registerCatalogProvider } from "./index.ts";

export function registerCatalogProviders(pi: ExtensionAPI): void {
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
