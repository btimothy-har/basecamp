/**
 * Custom header — launch summary banner above chat.
 *
 * Shows project, repo, worktree, branch, additional dirs, and working style
 * at session start. Static content — renders once from session state.
 */

import * as os from "node:os";
import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { getState } from "./session";

type ThemeFg = (color: Parameters<Theme["fg"]>[0], text: string) => string;

function shortenPath(p: string): string {
	const home = os.homedir();
	if (p.startsWith(home)) p = `~${p.slice(home.length)}`;
	return p;
}

function buildBanner(fg: ThemeFg, width: number): string[] {
	const state = getState();
	const lines: string[] = [];

	// Title line
	const title = state.projectName
		? `${fg("accent", "basecamp")} ${fg("dim", "·")} ${fg("text", state.projectName)}`
		: fg("accent", "basecamp");
	lines.push(title);

	// Info rows
	const rows: [string, string][] = [];

	rows.push(["Primary", shortenPath(state.primaryDir)]);

	if (state.worktreeLabel) {
		const branch = state.worktreeBranch ? fg("dim", ` (${state.worktreeBranch})`) : "";
		rows.push(["Worktree", `${state.worktreeLabel}${branch}`]);
	}

	if (state.secondaryDirs.length > 0) {
		rows.push(["Added dirs", state.secondaryDirs.map(shortenPath).join(", ")]);
	}

	rows.push(["Style", state.workingStyle]);

	// Render rows with aligned labels
	const labelWidth = Math.max(...rows.map(([label]) => label.length));
	for (const [label, value] of rows) {
		const padded = label.padEnd(labelWidth);
		lines.push(`  ${fg("dim", padded)}  ${value}`);
	}

	// Separator
	lines.push(fg("dim", "─".repeat(Math.min(width, 48))));

	return lines;
}

export function registerHeader(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		if (!ctx.hasUI) return;

		ctx.ui.setHeader((_tui, theme) => {
			const fg = theme.fg.bind(theme);

			return {
				render(width: number): string[] {
					return buildBanner(fg, width);
				},
				invalidate() {},
			};
		});
	});
}
