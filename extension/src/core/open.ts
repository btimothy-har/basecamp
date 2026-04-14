/**
 * /open command — open VS Code with project directories.
 *
 * Reads project config, builds a .code-workspace file, and opens it.
 * Uses the current session's project state if available.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { type SessionState, readConfig } from "./config";

const WORKSPACES_DIR = path.join(os.homedir(), ".workspaces");

function resolveDir(dir: string): string {
	if (path.isAbsolute(dir)) return dir;
	return path.join(os.homedir(), dir);
}

export function registerOpenCommand(
	pi: ExtensionAPI,
	getState: () => SessionState,
): void {
	pi.registerCommand("open", {
		description: "Open VS Code with project directories",
		handler: async (args, ctx) => {
			const state = getState();

			// Determine project name: arg overrides current session
			const projectName = args?.trim() || state.projectName;
			if (!projectName) {
				ctx.ui.notify("Usage: /open [project]", "error");
				return;
			}

			// Resolve project dirs
			let dirs: string[];
			if (projectName === state.projectName && state.project) {
				dirs = state.project.dirs;
			} else {
				const config = readConfig();
				const project = config.projects?.[projectName];
				if (!project) {
					ctx.ui.notify(`Project '${projectName}' not found`, "error");
					return;
				}
				dirs = project.dirs;
			}

			if (dirs.length === 0) {
				ctx.ui.notify(`Project '${projectName}' has no directories`, "error");
				return;
			}

			// Resolve directories
			const resolved = dirs.map(resolveDir).filter((d) => {
				try { return fs.statSync(d).isDirectory(); } catch { return false; }
			});

			if (resolved.length === 0) {
				ctx.ui.notify("No valid directories found", "error");
				return;
			}

			// Use worktree dir if active
			const primary = state.worktreeDir ?? resolved[0];
			const secondary = resolved.slice(1);

			// Build workspace file
			const folders = [
				{ path: primary },
				...secondary.map((d) => ({ path: d })),
			];
			const workspace = JSON.stringify({ folders }, null, 2);

			fs.mkdirSync(WORKSPACES_DIR, { recursive: true });
			const wsFile = path.join(
				WORKSPACES_DIR,
				`${projectName}.code-workspace`,
			);
			fs.writeFileSync(wsFile, workspace);

			// Open VS Code
			const result = await pi.exec("code", ["-r", wsFile], {
				timeout: 10_000,
			});

			if (result.code === 0) {
				ctx.ui.notify(`Opened VS Code for ${projectName}`, "info");
			} else {
				ctx.ui.notify(
					`VS Code failed: ${result.stderr || "unknown error"}`,
					"error",
				);
			}
		},
	});
}
