import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { getOrCreateWorktree, type WorktreeResult } from "#core/git/worktrees/crud.ts";
import { readWorktreeSetupCommand } from "#core/host/config.ts";
import { resolveDaemonPaths } from "#core/hub/index.ts";
import { ADJ_ADJ_NOUN, generateName } from "#core/naming/index.ts";
import { runWorktreeSetup, type WorktreeSetupResult } from "#core/project/workspace/setup.ts";
import {
	getWorkspaceState,
	listWorkspaceWorktrees,
	type WorkspaceState,
	type WorkspaceWorktree,
} from "#core/project/workspace/state.ts";
import type { DaemonClient } from "#core/swarm/agents/client.ts";
import {
	getWorkstream,
	listWorkstreams,
	type WorkstreamDetail,
	type WorkstreamSummary,
} from "#core/swarm/agents/client.ts";
import { type HerdrWorkstreamOpenResult, openWorkstreamInHerdr } from "./herdr.ts";

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
		generateWorkstreamName: (isTaken) => generateName({ pattern: ADJ_ADJ_NOUN, isTaken }),
		getClient: async () => {
			const connection = await getConnection();
			if (!connection) return null;
			const { createDaemonClient } = await import("#core/swarm/agents/client.ts");
			return createDaemonClient(connection as Parameters<typeof createDaemonClient>[0]);
		},
		resolveSocketPath: () => process.env.BASECAMP_DAEMON_UDS ?? resolveDaemonPaths().socketPath,
		getWorkstreamDetail: (socketPath, identifier) => getWorkstream(socketPath, identifier),
		listWorkstreamSummaries: (socketPath, filter) => listWorkstreams(socketPath, filter),
	};
}

export { errorMessage } from "#core/errors.ts";

function shellQuote(s: string): string {
	return `'${s.replace(/'/g, "'\\''")}'`;
}

export function workstreamLaunchCommand(slug: string): string {
	return `pi --workstream=${slug}`;
}

export function workstreamLaunchCommandFromPath(path: string, slug: string): string {
	return `cd ${shellQuote(path)} && ${workstreamLaunchCommand(slug)}`;
}
