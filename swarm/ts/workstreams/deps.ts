import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readWorktreeSetupCommand } from "#core/platform/config.ts";
import {
	getWorkspaceState,
	listWorkspaceWorktrees,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "#core/platform/workspace.ts";
import { runWorktreeSetup, type WorktreeSetupResult } from "#core/workspace/setup.ts";
import { getOrCreateWorktree, type WorktreeResult } from "#core/workspace/worktree.ts";
import type { DaemonClient } from "../agents/daemon/client.ts";
import {
	getWorkstream,
	listWorkstreams,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "../agents/daemon/client.ts";
import { resolveDaemonPaths } from "../agents/daemon/paths.ts";
import { type HerdrWorkstreamOpenResult, openWorkstreamInHerdr } from "./herdr.ts";
import { generateWorkstreamName as generateGenericWorkstreamName } from "./name.ts";

export interface WorkstreamToolsDeps {
	getWorkspaceState(): WorkspaceState | null;
	listWorkspaceWorktrees(): Promise<WorkspaceWorktree[]>;
	getOrCreateWorktree(
		pi: ExtensionAPI,
		repoRoot: string,
		repoName: string,
		label: string,
		branchName: string | null,
	): Promise<WorktreeResult>;
	readWorktreeSetupCommand(repoName: string): string | null;
	runWorktreeSetup(
		pi: ExtensionAPI,
		opts: { command: string; worktreeDir: string; repoRoot: string },
	): Promise<WorktreeSetupResult>;
	openWorkstreamInHerdr(
		pi: Pick<ExtensionAPI, "exec">,
		workspace: { protectedRoot?: string; repo?: { root?: string }; launchCwd?: string; hasUI?: boolean },
		worktree: { path: string; label: string },
		env: NodeJS.ProcessEnv,
	): Promise<HerdrWorkstreamOpenResult>;
	generateWorkstreamName(isTaken: (name: string) => boolean): string;
	getClient(): Promise<DaemonClient | null>;
	resolveSocketPath(): string;
	getWorkstreamDetail(socketPath: string, identifier: string): Promise<WorkstreamDetail | null>;
	listWorkstreamSummaries(
		socketPath: string,
		filter: { status?: string; repo?: string; dossierPath?: string; query?: string },
	): Promise<WorkstreamSummary[] | null>;
}

export function defaultWorkstreamToolsDeps(getConnection: () => Promise<unknown>): WorkstreamToolsDeps {
	return {
		getWorkspaceState,
		listWorkspaceWorktrees,
		getOrCreateWorktree,
		readWorktreeSetupCommand,
		runWorktreeSetup,
		openWorkstreamInHerdr,
		generateWorkstreamName: (isTaken) => generateGenericWorkstreamName({ isTaken }),
		getClient: async () => {
			const connection = await getConnection();
			if (!connection) return null;
			const { createDaemonClient } = await import("../agents/daemon/client.ts");
			return createDaemonClient(connection as Parameters<typeof createDaemonClient>[0]);
		},
		resolveSocketPath: () => process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
		getWorkstreamDetail: (socketPath, identifier) => getWorkstream(socketPath, identifier),
		listWorkstreamSummaries: (socketPath, filter) => listWorkstreams(socketPath, filter),
	};
}

export { errorMessage } from "../agents/errors.ts";

function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

export function workstreamLaunchCommand(slug: string): string {
	return `pi --workstream=${slug}`;
}

export function workstreamLaunchCommandFromPath(path: string, slug: string): string {
	return `cd ${shellQuote(path)} && ${workstreamLaunchCommand(slug)}`;
}
