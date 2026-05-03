/**
 * Custom header — launch summary banner above chat.
 *
 * Shows project, repo, worktree, branch, additional dirs, and working style
 * at session start. Static content — renders once from session state.
 */

import * as os from "node:os";
import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { truncateToWidth } from "@mariozechner/pi-tui";
import { getProjectState } from "../../../platform/session";
import { getWorkspaceState } from "../../../platform/workspace";

type ThemeFg = (color: Parameters<Theme["fg"]>[0], text: string) => string;

function shortenPath(p: string): string {
	const home = os.homedir();
	if (p.startsWith(home)) p = `~${p.slice(home.length)}`;
	return p;
}

function buildBanner(fg: ThemeFg, width: number): string[] {
	const workspace = getWorkspaceState();
	const project = getProjectState();
	const activeWorktree = workspace?.activeWorktree ?? null;
	const protectedRoot = workspace?.protectedRoot ?? workspace?.repo?.root ?? null;
	const lines: string[] = [];

	// Title line
	const title = project?.projectName
		? `${fg("accent", "basecamp")} ${fg("dim", "·")} ${fg("text", project.projectName)}`
		: fg("accent", "basecamp");
	lines.push(truncateToWidth(title, width, fg("dim", "…")));

	// Info rows
	const rows: [string, string][] = [];

	if (protectedRoot) {
		rows.push(["Protected", shortenPath(protectedRoot)]);
	}

	if (activeWorktree) {
		const branch = activeWorktree.branch ? fg("dim", ` (${activeWorktree.branch})`) : "";
		rows.push(["Worktree", `${activeWorktree.label}${branch} ${fg("dim", "·")} ${shortenPath(activeWorktree.path)}`]);
	} else {
		rows.push(["Worktree", "not active"]);
	}

	if (workspace?.unsafeEdit) {
		rows.push(["Unsafe edit", `${fg("error", "active")} ${fg("dim", "(--unsafe-edit)")}`]);
	}

	const additionalDirs = project?.additionalDirs ?? [];
	if (additionalDirs.length > 0) {
		for (let i = 0; i < additionalDirs.length; i++) {
			const label = i === 0 ? "Added dirs" : "";
			rows.push([label, shortenPath(additionalDirs[i]!)]);
		}
	}

	rows.push(["Style", project?.workingStyle ?? "engineering"]);

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
