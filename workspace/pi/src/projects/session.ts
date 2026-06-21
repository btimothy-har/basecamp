import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerWorkspaceAllowedRootsProvider, requireWorkspaceState } from "pi-core/platform/workspace.ts";
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
	});
}
