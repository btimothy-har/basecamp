/**
 * Core session bootstrap — Basecamp project state.
 */

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { resolveBasecampProjectState } from "../../../platform/config";
import {
	getBasecampProjectState,
	requireBasecampProjectState,
	resetBasecampProjectRuntime,
	setBasecampProjectState,
} from "../../../platform/project";
import { registerWorkspaceAllowedRootsProvider, requireWorkspaceState } from "../../../platform/workspace";
import { resetAgentMode } from "./mode";

function setBasecampProjectEnv(): void {
	process.env.BASECAMP_PROJECT = getBasecampProjectState()?.projectName ?? "";
}

export function registerSession(pi: ExtensionAPI): void {
	pi.registerFlag("style", {
		description: "Override working style (e.g. engineering, advisor)",
		type: "string",
	});
	pi.registerFlag("agent-prompt", {
		description: "Agent prompt file — replaces working style + system.md (used by worker spawner)",
		type: "string",
	});

	registerWorkspaceAllowedRootsProvider({
		id: "basecamp-project",
		roots: () => getBasecampProjectState()?.additionalDirs ?? [],
	});

	pi.on("session_start", async (_event, ctx) => {
		resetAgentMode();
		resetBasecampProjectRuntime();

		const workspaceState = requireWorkspaceState();
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const projectState = resolveBasecampProjectState({
			repoRoot: workspaceState.repo?.root ?? workspaceState.launchCwd,
			isRepo: workspaceState.repo !== null,
			styleOverride,
		});
		setBasecampProjectState(projectState);
		setBasecampProjectEnv();

		for (const warning of requireBasecampProjectState().projectWarnings) {
			ctx.ui.notify(`basecamp: ${warning}`, "warning");
		}

		const latestWorkspaceState = requireWorkspaceState();
		const latestProjectState = requireBasecampProjectState();
		const repoName = latestWorkspaceState.repo?.name ?? path.basename(latestWorkspaceState.scratchDir);
		const parts = [`repo=${repoName}`];
		if (latestProjectState.projectName) parts.push(`project=${latestProjectState.projectName}`);
		if (latestWorkspaceState.activeWorktree?.label) parts.push(`worktree=${latestWorkspaceState.activeWorktree.label}`);
		ctx.ui.notify(`basecamp: ${parts.join(", ")}`, "info");
	});
}
