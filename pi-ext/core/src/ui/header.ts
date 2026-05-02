/**
 * Custom header — launch summary banner above chat.
 *
 * Shows project, repo, worktree, branch, additional dirs, and working style
 * at session start. Static content — renders once from session state.
 */

import * as os from "node:os";
import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { truncateToWidth } from "@mariozechner/pi-tui";
import { getState } from "../runtime/session";

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
	lines.push(truncateToWidth(title, width, fg("dim", "…")));

	// Info rows
	const rows: [string, string][] = [];

	rows.push(["Protected", shortenPath(state.repoRoot)]);

	if (state.worktreeLabel && state.worktreeDir) {
		const branch = state.worktreeBranch ? fg("dim", ` (${state.worktreeBranch})`) : "";
		rows.push(["Worktree", `${state.worktreeLabel}${branch} ${fg("dim", "·")} ${shortenPath(state.worktreeDir)}`]);
	} else {
		rows.push(["Worktree", "not active"]);
	}

	if (state.unsafeEdit) {
		rows.push(["Unsafe edit", `${fg("error", "active")} ${fg("dim", "(--unsafe-edit)")}`]);
	}

	if (state.additionalDirs.length > 0) {
		for (let i = 0; i < state.additionalDirs.length; i++) {
			const label = i === 0 ? "Added dirs" : "";
			rows.push([label, shortenPath(state.additionalDirs[i]!)]);
		}
	}

	rows.push(["Style", state.workingStyle]);

	// Render rows with aligned labels, truncated to terminal width
	const labelWidth = Math.max(...rows.map(([label]) => label.length));
	for (const [label, value] of rows) {
		const padded = label.padEnd(labelWidth);
		const line = `  ${fg("dim", padded)}  ${value}`;
		lines.push(truncateToWidth(line, width, fg("dim", "…")));
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
