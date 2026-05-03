import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type ModelAlias, registerModelAliasProvider } from "../../platform/model-aliases.ts";
import { readModelAliasConfig } from "./config.ts";

const PROVIDER_ID = "native-config";

export default function (_pi: ExtensionAPI): void {
	const aliases = readModelAliasConfig();

	registerModelAliasProvider({
		id: PROVIDER_ID,
		resolve(alias: string): string | undefined {
			return aliases[alias];
		},
		list(): ModelAlias[] {
			return Object.entries(aliases).map(([alias, model]) => ({
				alias,
				model,
				providerId: PROVIDER_ID,
			}));
		},
	});
}
