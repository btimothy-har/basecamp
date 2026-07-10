/** Model-alias TUI forms: list overlay, detail overlay, pre-filled prompt. */

import type { ExtensionCommandContext, Theme } from "@earendil-works/pi-coding-agent";
import { DynamicBorder, getSelectListTheme } from "@earendil-works/pi-coding-agent";
import { Container, Editor, type EditorTheme, matchesKey, Spacer, Text } from "@earendil-works/pi-tui";
import { defaultModelAliasConfigPath, readModelAliasConfig } from "./aliases.ts";

type AliasEntry = { alias: string; model: string };
export type ListResult = { action: "add" } | { action: "detail"; alias: string };
export type DetailResult = "back" | "edit" | "rename" | "delete";

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

export async function showAliasList(ctx: ExtensionCommandContext): Promise<ListResult | undefined> {
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
				} else if (matchesKey(data, "a") || matchesKey(data, "shift+a")) {
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

export async function showAliasDetail(alias: string, ctx: ExtensionCommandContext): Promise<DetailResult> {
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
				} else if (matchesKey(data, "e") || matchesKey(data, "shift+e")) {
					done("edit");
				} else if (matchesKey(data, "r") || matchesKey(data, "shift+r")) {
					done("rename");
				} else if (matchesKey(data, "d") || matchesKey(data, "shift+d")) {
					done("delete");
				}
			},
		};
	});
}

export async function promptWithInitialValue(
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
