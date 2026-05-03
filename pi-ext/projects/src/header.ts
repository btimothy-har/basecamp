import * as os from "node:os";
import type { ExtensionAPI, Theme } from "@mariozechner/pi-coding-agent";
import { truncateToWidth } from "@mariozechner/pi-tui";
import { getWorkspaceState } from "../../platform/workspace.ts";
import { getProjectState } from "./project.ts";

type ThemeFg = (color: Parameters<Theme["fg"]>[0], text: string) => string;

function shortenPath(p: string): string {
	const home = os.homedir();
	return p.startsWith(home) ? `~${p.slice(home.length)}` : p;
}

function buildBanner(fg: ThemeFg, width: number): string[] {
	const workspace = getWorkspaceState();
	const project = getProjectState();
	const activeWorktree = workspace?.activeWorktree ?? null;
	const protectedRoot = workspace?.protectedRoot ?? workspace?.repo?.root ?? null;
	const lines: string[] = [];
	const title = project?.projectName
		? `${fg("accent", "projects")} ${fg("dim", "·")} ${fg("text", project.projectName)}`
		: fg("accent", "projects");
	lines.push(truncateToWidth(title, width, fg("dim", "…")));

	const rows: [string, string][] = [];
	if (protectedRoot) rows.push(["Protected", shortenPath(protectedRoot)]);
	if (activeWorktree) {
		const branch = activeWorktree.branch ? fg("dim", ` (${activeWorktree.branch})`) : "";
		rows.push(["Worktree", `${activeWorktree.label}${branch} ${fg("dim", "·")} ${shortenPath(activeWorktree.path)}`]);
	} else {
		rows.push(["Worktree", "not active"]);
	}
	if (workspace?.unsafeEdit) rows.push(["Unsafe edit", `${fg("error", "active")} ${fg("dim", "(--unsafe-edit)")}`]);

	const additionalDirs = project?.additionalDirs ?? [];
	for (let i = 0; i < additionalDirs.length; i++) {
		rows.push([i === 0 ? "Added dirs" : "", shortenPath(additionalDirs[i]!)]);
	}

	rows.push(["Style", project?.workingStyle ?? "engineering"]);

	const labelWidth = Math.max(...rows.map(([label]) => label.length));
	for (const [label, value] of rows) {
		const line = `  ${fg("dim", label.padEnd(labelWidth))}  ${value}`;
		lines.push(truncateToWidth(line, width, fg("dim", "…")));
	}
	lines.push(fg("dim", "─".repeat(Math.min(width, 48))));
	return lines;
}

export function registerHeader(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		if (!ctx.hasUI) return;

		ctx.ui.setHeader((_tui, theme) => ({
			invalidate() {},
			render(width: number): string[] {
				return buildBanner(theme.fg.bind(theme), width);
			},
		}));
	});
}
