/** /model-aliases command — alias CRUD flows over the forms in alias-forms.ts. */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { promptWithInitialValue, showAliasDetail, showAliasList } from "./alias-forms.ts";
import { type ConfiguredModelAliases, loadModelAliasConfig, writeModelAliasConfig } from "./config.ts";

type DeleteResult = "back" | "stay";

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

function readLatestAliasesForMutation(ctx: ExtensionCommandContext): ConfiguredModelAliases | null {
	const result = loadModelAliasConfig();
	if (!result.ok) {
		ctx.ui.notify(`Cannot update model aliases: ${result.error}`, "error");
		return null;
	}
	return { ...result.aliases };
}

function writeAliasesForMutation(ctx: ExtensionCommandContext, aliases: ConfiguredModelAliases): boolean {
	try {
		writeModelAliasConfig(aliases);
		return true;
	} catch (error) {
		ctx.ui.notify(`Failed to update model aliases: ${errorMessage(error)}`, "error");
		return false;
	}
}

async function addAlias(ctx: ExtensionCommandContext): Promise<void> {
	const aliasInput = await ctx.ui.input("Alias name");
	if (aliasInput === undefined) return;

	const alias = aliasInput.trim();
	if (alias === "") {
		ctx.ui.notify("Alias name is required.", "error");
		return;
	}

	const modelInput = await ctx.ui.input("Model name");
	if (modelInput === undefined) return;

	const model = modelInput.trim();
	if (model === "") {
		ctx.ui.notify("Model name is required.", "error");
		return;
	}

	const aliases = readLatestAliasesForMutation(ctx);
	if (!aliases) return;
	if (aliases[alias] !== undefined) {
		ctx.ui.notify(`Alias "${alias}" already exists.`, "error");
		return;
	}

	aliases[alias] = model;
	if (!writeAliasesForMutation(ctx, aliases)) return;
	ctx.ui.notify(`Added model alias "${alias}".`, "info");
}

async function editAliasModel(alias: string, ctx: ExtensionCommandContext): Promise<void> {
	const currentAliases = readLatestAliasesForMutation(ctx);
	if (!currentAliases) return;

	const currentModel = currentAliases[alias];
	if (currentModel === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return;
	}

	const modelInput = await promptWithInitialValue(ctx, "Model name", currentModel);
	if (modelInput === undefined) return;

	const model = modelInput.trim();
	if (model === "") {
		ctx.ui.notify("Model name is required.", "error");
		return;
	}

	const aliases = readLatestAliasesForMutation(ctx);
	if (!aliases) return;
	if (aliases[alias] === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return;
	}

	aliases[alias] = model;
	if (!writeAliasesForMutation(ctx, aliases)) return;
	ctx.ui.notify(`Updated model alias "${alias}".`, "info");
}

async function renameAlias(alias: string, ctx: ExtensionCommandContext): Promise<string | undefined> {
	const aliasInput = await promptWithInitialValue(ctx, "Alias name", alias);
	if (aliasInput === undefined) return undefined;

	const nextAlias = aliasInput.trim();
	if (nextAlias === "") {
		ctx.ui.notify("Alias name is required.", "error");
		return undefined;
	}
	if (nextAlias === alias) return alias;

	const aliases = readLatestAliasesForMutation(ctx);
	if (!aliases) return undefined;
	const model = aliases[alias];
	if (model === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return undefined;
	}
	if (aliases[nextAlias] !== undefined) {
		ctx.ui.notify(`Alias "${nextAlias}" already exists.`, "error");
		return undefined;
	}

	delete aliases[alias];
	aliases[nextAlias] = model;
	if (!writeAliasesForMutation(ctx, aliases)) return undefined;
	ctx.ui.notify(`Renamed model alias "${alias}" to "${nextAlias}".`, "info");
	return nextAlias;
}

async function deleteAlias(alias: string, ctx: ExtensionCommandContext): Promise<DeleteResult> {
	const currentAliases = readLatestAliasesForMutation(ctx);
	if (!currentAliases) return "stay";

	const model = currentAliases[alias];
	if (model === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return "back";
	}

	const confirmed = await ctx.ui.confirm("Delete model alias?", `Delete "${alias}" → "${model}"?`);
	if (!confirmed) return "stay";

	const aliases = readLatestAliasesForMutation(ctx);
	if (!aliases) return "stay";
	if (aliases[alias] === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return "back";
	}

	delete aliases[alias];
	if (!writeAliasesForMutation(ctx, aliases)) return "stay";
	ctx.ui.notify(`Deleted model alias "${alias}".`, "info");
	return "back";
}

export function registerModelAliasCommands(pi: ExtensionAPI): void {
	pi.registerCommand("model-aliases", {
		description: "Manage native model aliases",
		handler: async (_args, ctx) => {
			if (!ctx.hasUI) {
				ctx.ui.notify("The /model-aliases command requires an interactive UI.", "info");
				return;
			}

			let listResult = await showAliasList(ctx);
			while (listResult !== undefined) {
				if (listResult.action === "add") {
					await addAlias(ctx);
				} else {
					let alias = listResult.alias;
					let detailResult = await showAliasDetail(alias, ctx);
					while (detailResult !== "back") {
						if (detailResult === "edit") {
							await editAliasModel(alias, ctx);
						} else if (detailResult === "rename") {
							alias = (await renameAlias(alias, ctx)) ?? alias;
						} else if (detailResult === "delete") {
							if ((await deleteAlias(alias, ctx)) === "back") break;
						}
						detailResult = await showAliasDetail(alias, ctx);
					}
				}
				listResult = await showAliasList(ctx);
			}
		},
	});
}
