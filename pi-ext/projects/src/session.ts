import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { registerWorkspaceAllowedRootsProvider, requireWorkspaceState } from "../../platform/workspace.ts";
import { resolveProjectState } from "./config.ts";
import { getProjectState, requireProjectState, resetProjectRuntime, setProjectState } from "./project.ts";

function setProjectEnv(): void {
	process.env.BASECAMP_PROJECT = getProjectState()?.projectName ?? "";
}

export function registerProjectSession(pi: ExtensionAPI): void {
	pi.registerFlag("style", {
		description: "Override working style (e.g. engineering, advisor)",
		type: "string",
	});
	pi.registerFlag("agent-prompt", {
		description: "Agent prompt file — replaces working style + system.md (used by worker spawner)",
		type: "string",
	});

	registerWorkspaceAllowedRootsProvider({
		id: "projects",
		roots: () => getProjectState()?.additionalDirs ?? [],
	});

	pi.on("session_start", async (_event, ctx) => {
		resetProjectRuntime();

		const workspaceState = requireWorkspaceState();
		const styleOverride = (pi.getFlag("style") as string | undefined) ?? undefined;
		const projectState = resolveProjectState({
			repoRoot: workspaceState.repo?.root ?? workspaceState.launchCwd,
			isRepo: workspaceState.repo !== null,
			styleOverride,
		});
		setProjectState(projectState);
		setProjectEnv();

		for (const warning of requireProjectState().warnings) {
			ctx.ui.notify(`projects: ${warning}`, "warning");
		}

		const latestWorkspaceState = requireWorkspaceState();
		const latestProjectState = requireProjectState();
		const repoName = latestWorkspaceState.repo?.name ?? path.basename(latestWorkspaceState.scratchDir);
		const parts = [`repo=${repoName}`];
		if (latestProjectState.projectName) parts.push(`project=${latestProjectState.projectName}`);
		if (latestWorkspaceState.activeWorktree?.label) parts.push(`worktree=${latestWorkspaceState.activeWorktree.label}`);
		ctx.ui.notify(`projects: ${parts.join(", ")}`, "info");
	});
}
