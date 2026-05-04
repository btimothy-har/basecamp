import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type ModelAlias, registerModelAliasProvider } from "../platform/model-aliases.ts";
import { readModelAliasConfig } from "./config.ts";

const PROVIDER_ID = "native-config";

export default function (_pi: ExtensionAPI): void {
	registerModelAliasProvider({
		id: PROVIDER_ID,
		resolve(alias: string): string | undefined {
			return readModelAliasConfig()[alias];
		},
		list(): ModelAlias[] {
			return Object.entries(readModelAliasConfig()).map(([alias, model]) => ({
				alias,
				model,
				providerId: PROVIDER_ID,
			}));
		},
	});
}
