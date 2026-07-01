import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState, WorkspaceWorktree } from "pi-core/platform/workspace.ts";

export const HERDR_WORKTREE_OPEN_TIMEOUT_MS = 5_000;

export interface HerdrWorktreeEnv {
	BASECAMP_AGENT_DEPTH?: string;
	HERDR_ENV?: string;
	HERDR_PANE_ID?: string;
	HERDR_SOCKET_PATH?: string;
	HERDR_WORKSPACE_ID?: string;
}

export function isPrimaryHerdrSession(env: HerdrWorktreeEnv = process.env): boolean {
	return (
		env.HERDR_ENV === "1" &&
		!!env.HERDR_SOCKET_PATH &&
		!!env.HERDR_PANE_ID &&
		Number(env.BASECAMP_AGENT_DEPTH ?? "0") === 0
	);
}

export function buildHerdrWorktreeOpenArgs(
	state: WorkspaceState,
	activeWorktree: WorkspaceWorktree,
	env: HerdrWorktreeEnv = process.env,
): string[] | null {
	if (!isPrimaryHerdrSession(env)) return null;

	const args = ["worktree", "open"];
	if (env.HERDR_WORKSPACE_ID) {
		args.push("--workspace", env.HERDR_WORKSPACE_ID);
	} else {
		const cwd = state.protectedRoot ?? state.repo?.root ?? state.launchCwd;
		if (cwd) args.push("--cwd", cwd);
	}

	args.push("--path", activeWorktree.path, "--label", activeWorktree.label, "--no-focus", "--json");
	return args;
}

export async function openActiveWorktreeInHerdr(
	pi: ExtensionAPI,
	state: WorkspaceState,
	activeWorktree: WorkspaceWorktree,
	env: HerdrWorktreeEnv = process.env,
): Promise<void> {
	try {
		const args = buildHerdrWorktreeOpenArgs(state, activeWorktree, env);
		if (!args) return;
		await pi.exec("herdr", args, { timeout: HERDR_WORKTREE_OPEN_TIMEOUT_MS });
	} catch {
		/* Herdr sync is best-effort and must never interrupt Basecamp activation. */
	}
}
