import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type ModelAlias, type ModelAliasProvider, registerModelAliasProvider } from "../platform/model-aliases.ts";
import { registerModelAliasCommands } from "./commands.ts";
import { readModelAliasConfig } from "./config.ts";

const PROVIDER_ID = "native-config";

export function createNativeConfigModelAliasProvider(configPath?: string): ModelAliasProvider {
	return {
		id: PROVIDER_ID,
		resolve(alias: string): string | undefined {
			return readModelAliasConfig(configPath)[alias];
		},
		list(): ModelAlias[] {
			return Object.entries(readModelAliasConfig(configPath)).map(([alias, model]) => ({
				alias,
				model,
				providerId: PROVIDER_ID,
			}));
		},
	};
}

export default function (pi: ExtensionAPI): void {
	registerModelAliasProvider(createNativeConfigModelAliasProvider());
	registerModelAliasCommands(pi);
}
