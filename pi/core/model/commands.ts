/** /model-aliases command — alias CRUD flows over the forms in alias-forms.ts. */

import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { exec } from "../host/exec.ts";
import { promptWithInitialValue, showAliasDetail, showAliasList } from "./alias-forms.ts";
import { type ConfiguredModelAliases, errorMessage, loadModelAliasConfig } from "./aliases.ts";

type DeleteResult = "back" | "stay";

function readLatestAliasesForMutation(ctx: ExtensionCommandContext): ConfiguredModelAliases | null {
	const result = loadModelAliasConfig();
	if (!result.ok) {
		ctx.ui.notify(`Cannot update model aliases: ${result.error}`, "error");
		return null;
	}
	return { ...result.aliases };
}

// Python is the sole config writer; alias mutations shell out to the flock'd
// `basecamp config alias` CLI (reads above stay in-process).
async function runConfigAlias(
	ctx: ExtensionCommandContext,
	pi: ExtensionAPI,
	args: string[],
	failVerb: string,
): Promise<boolean> {
	try {
		const result = await exec(pi, "basecamp", ["config", "alias", ...args]);
		if (result.code !== 0) {
			const detail = result.stderr.trim() || `basecamp exited ${result.code}`;
			ctx.ui.notify(`Failed to ${failVerb} model alias: ${detail}`, "error");
			return false;
		}
		return true;
	} catch (error) {
		ctx.ui.notify(`Failed to ${failVerb} model alias: ${errorMessage(error)}`, "error");
		return false;
	}
}

function setAliasViaCli(
	ctx: ExtensionCommandContext,
	pi: ExtensionAPI,
	alias: string,
	model: string,
): Promise<boolean> {
	return runConfigAlias(ctx, pi, ["set", alias, model], "save");
}

function removeAliasViaCli(ctx: ExtensionCommandContext, pi: ExtensionAPI, alias: string): Promise<boolean> {
	return runConfigAlias(ctx, pi, ["remove", alias], "remove");
}

async function addAlias(ctx: ExtensionCommandContext, pi: ExtensionAPI): Promise<void> {
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

	if (!(await setAliasViaCli(ctx, pi, alias, model))) return;
	ctx.ui.notify(`Added model alias "${alias}".`, "info");
}

async function editAliasModel(alias: string, ctx: ExtensionCommandContext, pi: ExtensionAPI): Promise<void> {
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

	if (!(await setAliasViaCli(ctx, pi, alias, model))) return;
	ctx.ui.notify(`Updated model alias "${alias}".`, "info");
}

async function renameAlias(alias: string, ctx: ExtensionCommandContext, pi: ExtensionAPI): Promise<string | undefined> {
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

	// Rename = create the new alias, then drop the old one.
	if (!(await setAliasViaCli(ctx, pi, nextAlias, model))) return undefined;
	if (!(await removeAliasViaCli(ctx, pi, alias))) return nextAlias;
	ctx.ui.notify(`Renamed model alias "${alias}" to "${nextAlias}".`, "info");
	return nextAlias;
}

async function deleteAlias(alias: string, ctx: ExtensionCommandContext, pi: ExtensionAPI): Promise<DeleteResult> {
	const currentAliases = readLatestAliasesForMutation(ctx);
	if (!currentAliases) return "stay";

	const model = currentAliases[alias];
	if (model === undefined) {
		ctx.ui.notify(`Alias "${alias}" no longer exists.`, "error");
		return "back";
	}

	const confirmed = await ctx.ui.confirm("Delete model alias?", `Delete "${alias}" → "${model}"?`);
	if (!confirmed) return "stay";

	if (!(await removeAliasViaCli(ctx, pi, alias))) return "stay";
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
					await addAlias(ctx, pi);
				} else {
					let alias = listResult.alias;
					let detailResult = await showAliasDetail(alias, ctx);
					while (detailResult !== "back") {
						if (detailResult === "edit") {
							await editAliasModel(alias, ctx, pi);
						} else if (detailResult === "rename") {
							alias = (await renameAlias(alias, ctx, pi)) ?? alias;
						} else if (detailResult === "delete") {
							if ((await deleteAlias(alias, ctx, pi)) === "back") break;
						}
						detailResult = await showAliasDetail(alias, ctx);
					}
				}
				listResult = await showAliasList(ctx);
			}
		},
	});
}
