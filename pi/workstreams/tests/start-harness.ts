/** Shared scaffolding for the workstream-startup test suites (start.test.ts, start-daemon.test.ts). */

import type { ExtensionContext, SessionStartEvent } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState } from "#core/project/workspace/state.ts";
import type { DaemonClient, WorkstreamDetail } from "#core/swarm/agents/client.ts";
import type { WorkstreamStartDeps } from "../start.ts";

export function makeWorkstreamDetail(overrides: Partial<WorkstreamDetail> = {}): WorkstreamDetail {
	return {
		id: "ws-uuid-1",
		slug: "steady-amber-otter",
		label: "Launch Workstream Too",
		brief: "Implement the launch workstream tool.",
		constraints: null,
		source_dossier_path: "/graph/pages/Dossier.md",
		source_repo_page_path: null,
		status: "open",
		version: 1,
		created_at: "2026-07-03T00:00:00.000Z",
		updated_at: "2026-07-03T00:00:00.000Z",
		agent_count: 0,
		agents: [],
		versions: [],
		...overrides,
	};
}

export class FakeDaemonClient {
	readonly attachCalls: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}[] = [];
	private attachStatus: "attached" | "not_found" | "error" = "attached";

	setAttachStatus(status: "attached" | "not_found" | "error"): void {
		this.attachStatus = status;
	}

	async attachWorkstreamAgent(input: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}) {
		this.attachCalls.push(input);
		return { status: this.attachStatus, error: this.attachStatus === "error" ? "db error" : null };
	}
}

export function makeWorkspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		repo: { isRepo: true, name: "org/repo" },
		activeWorktree: {
			label: "copilot/steady-amber-otter",
			path: "/worktrees/org/repo/copilot/steady-amber-otter",
			branch: "bt/x",
			created: false,
		},
		...overrides,
	} as unknown as WorkspaceState;
}

export function makeCtx(): { ctx: ExtensionContext; notices: { message: string; level: string }[] } {
	const notices: { message: string; level: string }[] = [];
	const ctx = {
		hasUI: true,
		cwd: "/repo",
		ui: {
			notify(message: string, level: string) {
				notices.push({ message, level });
			},
		},
		sessionManager: { getSessionId: () => "session-abc" },
	} as unknown as ExtensionContext;
	return { ctx, notices };
}

export function makeDeps(client: FakeDaemonClient, overrides: Partial<WorkstreamStartDeps> = {}) {
	const enterExploreModeCalls: { event: SessionStartEvent; ctx: ExtensionContext }[] = [];
	let workspace: WorkspaceState | null = makeWorkspace();
	let waitedWorkspace: WorkspaceState | null = workspace;
	const workstreamDetails = new Map<string, WorkstreamDetail | null>();
	let detail: WorkstreamDetail | null = makeWorkstreamDetail();
	let priorTurns = false;

	const deps: WorkstreamStartDeps = {
		getWorkspaceState: () => workspace,
		waitForWorkspaceState: async () => waitedWorkspace,
		resolveSocketPath: () => "/tmp/daemon.sock",
		getWorkstreamDetail: async (_sp, identifier) => {
			if (workstreamDetails.has(identifier)) return workstreamDetails.get(identifier) ?? null;
			if (detail && (detail.slug === identifier || detail.id === identifier)) return detail;
			return null;
		},
		getClient: async () => client as unknown as DaemonClient,
		enterExploreMode: (event, ctx) => {
			enterExploreModeCalls.push({ event, ctx });
		},
		hasPriorTurns: () => priorTurns,
		...overrides,
	};

	return {
		deps,
		client,
		enterExploreModeCalls,
		setWorkspace(value: WorkspaceState | null) {
			workspace = value;
		},
		setWaitedWorkspace(value: WorkspaceState | null) {
			waitedWorkspace = value;
		},
		setDetail(value: WorkstreamDetail | null) {
			detail = value;
		},
		setWorkstreamDetail(identifier: string, value: WorkstreamDetail | null) {
			workstreamDetails.set(identifier, value);
		},
		setPriorTurns(value: boolean) {
			priorTurns = value;
		},
	};
}
