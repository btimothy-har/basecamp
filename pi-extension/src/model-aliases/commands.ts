import type { ExtensionAPI, ExtensionCommandContext, Theme } from "@mariozechner/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@mariozechner/pi-coding-agent";
import { Container, Editor, type EditorTheme, matchesKey, Spacer, Text } from "@mariozechner/pi-tui";
import {
	type ConfiguredModelAliases,
	defaultModelAliasConfigPath,
	loadModelAliasConfig,
	readModelAliasConfig,
	writeModelAliasConfig,
} from "./config.ts";

type AliasEntry = { alias: string; model: string };
type ListResult = { action: "add" } | { action: "detail"; alias: string };
type DetailResult = "back" | "edit" | "rename" | "delete";
type DeleteResult = "back" | "stay";

function getAliasEntries(): AliasEntry[] {
	return Object.entries(readModelAliasConfig())
		.map(([alias, model]) => ({ alias, model }))
		.sort((a, b) => a.alias.localeCompare(b.alias));
}

function renderAliasList(entries: AliasEntry[], selectedIdx: number, theme: Theme): string[] {
	if (entries.length === 0) {
		return [theme.fg("dim", "No model aliases configured."), "", "Press a to add your first alias."];
	}

	const lines: string[] = [];
	for (let i = 0; i < entries.length; i++) {
		const entry = entries[i]!;
		const isSelected = i === selectedIdx;
		const marker = isSelected ? theme.fg("accent", "▸") : " ";
		const alias = isSelected ? theme.fg("accent", theme.bold(entry.alias)) : theme.fg("toolTitle", entry.alias);
		lines.push(`${marker} ${alias} ${theme.fg("dim", "→")} ${entry.model}`);
	}
	return lines;
}

async function showAliasList(ctx: ExtensionCommandContext): Promise<ListResult | undefined> {
	return ctx.ui.custom<ListResult | undefined>((_tui, theme, _kb, done) => {
		let selected = 0;

		const header = new Text(theme.fg("accent", theme.bold("Model Aliases")), 1, 0);
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const hint = new Text(theme.fg("dim", "↑↓ navigate  Enter view  a add alias  Esc close"), 1, 0);
		const listText = new Text("", 0, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(header);
		container.addChild(new Spacer(1));
		container.addChild(listText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		function refreshEntries(): AliasEntry[] {
			const entries = getAliasEntries();
			selected = Math.min(selected, Math.max(0, entries.length - 1));
			return entries;
		}

		return {
			render: (_width: number) => {
				const entries = refreshEntries();
				listText.setText(renderAliasList(entries, selected, theme).join("\n"));
				return container.render(_width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				const entries = refreshEntries();
				if (matchesKey(data, "escape")) {
					done(undefined);
				} else if (matchesKey(data, "enter")) {
					const entry = entries[selected];
					if (entry) done({ action: "detail", alias: entry.alias });
				} else if (matchesKey(data, "up")) {
					if (selected > 0) {
						selected--;
						container.invalidate();
					}
				} else if (matchesKey(data, "down")) {
					if (selected < entries.length - 1) {
						selected++;
						container.invalidate();
					}
				} else if (data === "a" || data === "A") {
					done({ action: "add" });
				}
			},
		};
	});
}

function renderAliasDetail(alias: string, theme: Theme): string[] {
	const aliases = readModelAliasConfig();
	const model = aliases[alias];
	if (model === undefined) {
		return [theme.fg("dim", "Alias not found."), "", `${theme.fg("dim", "Alias")}  ${alias}`];
	}

	return [
		`${theme.fg("dim", "Alias")}  ${theme.fg("accent", theme.bold(alias))}`,
		`${theme.fg("dim", "Model")}  ${model}`,
		`${theme.fg("dim", "Config")} ${defaultModelAliasConfigPath()}`,
	];
}

async function showAliasDetail(alias: string, ctx: ExtensionCommandContext): Promise<DetailResult> {
	return ctx.ui.custom<DetailResult>((_tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const detailText = new Text("", 0, 0);
		const hint = new Text(theme.fg("dim", "e edit model  r rename alias  d delete  Esc back"), 1, 0);

		const container = new Container();
		container.addChild(border);
		container.addChild(new Spacer(1));
		container.addChild(detailText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				detailText.setText(renderAliasDetail(alias, theme).join("\n"));
				return container.render(width);
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape")) {
					done("back");
				} else if (data === "e" || data === "E") {
					done("edit");
				} else if (data === "r" || data === "R") {
					done("rename");
				} else if (data === "d" || data === "D") {
					done("delete");
				}
			},
		};
	});
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}

async function promptWithInitialValue(
	ctx: ExtensionCommandContext,
	label: string,
	initialValue: string,
): Promise<string | undefined> {
	return ctx.ui.custom<string | undefined>((tui, theme, _kb, done) => {
		const border = new DynamicBorder((s: string) => theme.fg("border", s));
		const labelText = new Text(theme.fg("accent", theme.bold(label)), 1, 0);
		const hint = new Text(theme.fg("dim", "Enter submit  Esc cancel"), 1, 0);

		const editorTheme: EditorTheme = {
			borderColor: (s: string) => theme.fg("dim", s),
			selectList: getSelectListTheme(),
		};
		const editor = new Editor(tui, editorTheme, { paddingX: 0 });
		editor.setText(initialValue);
		editor.focused = true;
		editor.onSubmit = (value: string) => {
			done(value);
		};

		const container = new Container();
		container.addChild(border);
		container.addChild(labelText);
		container.addChild(new Spacer(1));
		container.addChild(hint);
		container.addChild(border);

		return {
			render: (width: number) => {
				const lines = container.render(width);
				const editorLines = editor.render(width - 2);
				lines.splice(2, 0, ...editorLines);
				return lines;
			},
			invalidate: () => container.invalidate(),
			handleInput: (data: string) => {
				if (matchesKey(data, "escape")) {
					done(undefined);
					return;
				}
				editor.handleInput(data);
				container.invalidate();
			},
		};
	});
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
