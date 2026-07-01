import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";

export const HERDR_WORKSTREAM_OPEN_TIMEOUT_MS = 5_000;

export interface HerdrWorkstreamEnv {
	BASECAMP_AGENT_DEPTH?: string;
	HERDR_ENV?: string;
	HERDR_PANE_ID?: string;
	HERDR_SOCKET_PATH?: string;
	HERDR_WORKSPACE_ID?: string;
}

export interface HerdrWorkstreamWorktree {
	label: string;
	path: string;
}

export function shouldOpenWorkstreamInHerdr(env: HerdrWorkstreamEnv = process.env): boolean {
	return (
		env.HERDR_ENV === "1" &&
		!!env.HERDR_SOCKET_PATH &&
		!!env.HERDR_PANE_ID &&
		Number(env.BASECAMP_AGENT_DEPTH ?? "0") === 0
	);
}

export function buildHerdrWorkstreamOpenArgs(
	workspace: WorkspaceState,
	worktree: HerdrWorkstreamWorktree,
	env: HerdrWorkstreamEnv = process.env,
): string[] | null {
	if (!shouldOpenWorkstreamInHerdr(env)) return null;

	const args = ["worktree", "open"];
	if (env.HERDR_WORKSPACE_ID) {
		args.push("--workspace", env.HERDR_WORKSPACE_ID);
	} else {
		const cwd = workspace.protectedRoot ?? workspace.repo?.root ?? workspace.launchCwd;
		if (cwd) args.push("--cwd", cwd);
	}

	args.push("--path", worktree.path, "--label", worktree.label, "--no-focus", "--json");
	return args;
}

export async function openWorkstreamInHerdr(
	pi: ExtensionAPI,
	workspace: WorkspaceState,
	worktree: HerdrWorkstreamWorktree,
	env: HerdrWorkstreamEnv = process.env,
): Promise<void> {
	try {
		const args = buildHerdrWorkstreamOpenArgs(workspace, worktree, env);
		if (!args) return;
		await pi.exec("herdr", args, { timeout: HERDR_WORKSTREAM_OPEN_TIMEOUT_MS });
	} catch {
		/* Herdr sync is best-effort and must never interrupt workstream dispatch. */
	}
}
