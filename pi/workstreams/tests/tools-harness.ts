import { afterEach, beforeEach } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorktreeResult } from "#core/git/worktrees/crud.ts";
import type { WorkspaceState, WorkspaceWorktree } from "#core/project/workspace/state.ts";
import type { DaemonClient, WorkstreamDetail, WorkstreamSummary } from "#core/swarm/agents/client.ts";
import type { HerdrWorkstreamOpenResult } from "../herdr.ts";
import { executeLaunchWorkstream, type LaunchWorkstreamResultDetails, type WorkstreamToolsDeps } from "../tools.ts";

export function makeWorkstreamDetail(overrides: Partial<WorkstreamDetail> = {}): WorkstreamDetail {
	return {
		id: "ws-uuid-1",
		slug: "steady-amber-otter",
		label: "Alpha",
		brief: "Do the thing.",
		constraints: null,
		source_dossier_path: "/graph/pages/Dossier.md",
		source_repo_page_path: null,
		status: "open",
		created_at: "2026-07-03T00:00:00.000Z",
		updated_at: "2026-07-03T00:00:00.000Z",
		agent_count: 0,
		agents: [],
		...overrides,
	};
}

export function makeWorkstreamSummary(overrides: Partial<WorkstreamSummary> = {}): WorkstreamSummary {
	return {
		id: "ws-uuid-1",
		slug: "steady-amber-otter",
		label: "Alpha",
		brief: "Do the thing.",
		constraints: null,
		source_dossier_path: "/graph/pages/Dossier.md",
		source_repo_page_path: null,
		status: "open",
		created_at: "2026-07-03T00:00:00.000Z",
		updated_at: "2026-07-03T00:00:00.000Z",
		agent_count: 0,
		...overrides,
	};
}

interface FakeClientOptions {
	createStatus?: "created" | "slug_conflict" | "error";
	attachStatus?: "attached" | "not_found" | "error";
	updateStatus?: "updated" | "not_found" | "invalid_status" | "error";
	existingSlugs?: Set<string>;
	workstreamDetail?: WorkstreamDetail | null;
	workstreamSummaries?: WorkstreamSummary[] | null;
}

export class FakeDaemonClient {
	readonly createCalls: {
		workstreamId: string;
		slug: string;
		label: string;
		brief: string;
		sourceDossierPath: string;
		constraints?: string | null;
		sourceRepoPagePath?: string | null;
	}[] = [];
	readonly attachCalls: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}[] = [];
	readonly updateCalls: { workstream: string; status: "open" | "closed" }[] = [];
	private opts: FakeClientOptions;

	constructor(opts: FakeClientOptions = {}) {
		this.opts = opts;
	}

	setOpts(opts: Partial<FakeClientOptions>): void {
		this.opts = { ...this.opts, ...opts };
	}

	async createWorkstream(input: {
		workstreamId: string;
		slug: string;
		label: string;
		brief: string;
		sourceDossierPath: string;
		constraints?: string | null;
		sourceRepoPagePath?: string | null;
	}) {
		this.createCalls.push(input);
		const status = this.opts.createStatus ?? "created";
		if (status === "slug_conflict") {
			return { status: "slug_conflict" as const, workstream_id: null, slug: null, error: "slug taken" };
		}
		if (status === "error") {
			return { status: "error" as const, workstream_id: null, slug: null, error: "db error" };
		}
		return { status: "created" as const, workstream_id: input.workstreamId, slug: input.slug, error: null };
	}

	async attachWorkstreamAgent(input: {
		workstream: string;
		repo?: string | null;
		worktreeLabel?: string | null;
		status?: string;
		error?: string | null;
	}) {
		this.attachCalls.push(input);
		const status = this.opts.attachStatus ?? "attached";
		return { status: status as "attached" | "not_found" | "error", error: status === "error" ? "db error" : null };
	}

	async updateWorkstream(input: { workstream: string; status: "open" | "closed" }) {
		this.updateCalls.push(input);
		const status = this.opts.updateStatus ?? "updated";
		return {
			status: status as "updated" | "not_found" | "invalid_status" | "error",
			error: status === "error" ? "db error" : null,
		};
	}
}

export function makeWorkspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: "/repo",
		scratchDir: "/tmp/pi/basecamp",
		repo: {
			isRepo: true,
			name: "org/repo",
			root: "/repo",
			remoteUrl: "git@github.com:org/repo.git",
		},
		protectedRoot: "/repo",
		activeWorktree: null,
		unsafeEdit: false,
		...overrides,
	} as unknown as WorkspaceState;
}

function makeContext(): ExtensionContext {
	return {
		hasUI: true,
		sessionManager: {
			getSessionId() {
				return "018ff5a0-2222-7333-8444-000000008e95";
			},
		},
	} as unknown as ExtensionContext;
}

export function baseParams(overrides: Record<string, unknown> = {}) {
	return {
		source: {
			dossierPath: "/graph/pages/Dossier.md",
			repoPagePath: "/graph/pages/Repo.md",
		},
		workstream: {
			label: "Launch Workstream Too",
			brief: "Implement the launch workstream tool.",
			constraints: "Stay in scope.",
		},
		...overrides,
	};
}

export function makeDeps(client: FakeDaemonClient, overrides: Partial<WorkstreamToolsDeps> = {}) {
	const provisionCalls: { repoRoot: string; repoName: string; label: string; branchName: string | null }[] = [];
	const setupCalls: { command: string; worktreeDir: string; repoRoot: string }[] = [];
	const herdrCalls: { workspace: unknown; worktree: { path: string; label: string } }[] = [];
	let workspace: WorkspaceState | null = makeWorkspace();
	let listedWorktrees: WorkspaceWorktree[] = [];
	let setupCommand: string | null = null;
	let created = true;
	let provision: WorkstreamToolsDeps["getOrCreateWorktree"] = async (_pi, repoRoot, repoName, label, branchName) => {
		provisionCalls.push({ repoRoot, repoName, label, branchName });
		return {
			worktreeDir: `/worktrees/org/repo/${label}`,
			label,
			branch: branchName ?? label,
			created,
		} satisfies WorktreeResult;
	};
	let setupResult = { ran: true, exitCode: 0, timedOut: false, stderrTail: "" };
	let herdrResult: HerdrWorkstreamOpenResult = { status: "opened", message: "Herdr workstream opened.", args: [] };
	let slugSeq = 0;
	const slugCandidates = ["steady-amber-otter", "calm-cedar-heron", "bright-maple-fox"];
	const workstreamDetails = new Map<string, WorkstreamDetail | null>();
	let workstreamSummaries: WorkstreamSummary[] | null = [];

	const deps: WorkstreamToolsDeps = {
		getWorkspaceState: () => workspace,
		listWorkspaceWorktrees: async () => listedWorktrees,
		getOrCreateWorktree: (pi, repoRoot, repoName, label, branchName) =>
			provision(pi, repoRoot, repoName, label, branchName),
		readWorktreeSetupCommand: () => setupCommand,
		runWorktreeSetup: async (_pi, opts) => {
			setupCalls.push(opts);
			return setupResult;
		},
		openWorkstreamInHerdr: async (_pi, herdrWorkspace, worktree) => {
			herdrCalls.push({ workspace: herdrWorkspace, worktree });
			return herdrResult;
		},
		generateWorkstreamName: () => {
			const candidate = slugCandidates[slugSeq % slugCandidates.length] ?? "fresh-river-lark";
			slugSeq += 1;
			return candidate;
		},
		getClient: async () => client as unknown as DaemonClient,
		resolveSocketPath: () => "/tmp/daemon.sock",
		getWorkstreamDetail: async (_socketPath, identifier) => {
			if (workstreamDetails.has(identifier)) return workstreamDetails.get(identifier) ?? null;
			return null;
		},
		listWorkstreamSummaries: async () => workstreamSummaries,
		...overrides,
	};

	return {
		deps,
		client,
		provisionCalls,
		setupCalls,
		herdrCalls,
		setWorkspace(value: WorkspaceState | null) {
			workspace = value;
		},
		setListedWorktrees(value: WorkspaceWorktree[]) {
			listedWorktrees = value;
		},
		setSetupCommand(value: string | null) {
			setupCommand = value;
		},
		setCreated(value: boolean) {
			created = value;
		},
		setProvision(value: WorkstreamToolsDeps["getOrCreateWorktree"]) {
			provision = value;
		},
		setSetupResult(value: typeof setupResult) {
			setupResult = value;
		},
		setHerdrResult(value: typeof herdrResult) {
			herdrResult = value;
		},
		setWorkstreamDetail(slug: string, detail: WorkstreamDetail | null) {
			workstreamDetails.set(slug, detail);
		},
		setWorkstreamSummaries(value: WorkstreamSummary[] | null) {
			workstreamSummaries = value;
		},
		resetSlugSeq() {
			slugSeq = 0;
		},
	};
}

export async function runLaunch(params: unknown, deps: WorkstreamToolsDeps) {
	const pi = { exec: async () => ({ code: 0, stdout: "", stderr: "", killed: false }) } as unknown as ExtensionAPI;
	const result = await executeLaunchWorkstream(params, pi, makeContext(), undefined, deps);
	return { result, details: result.details as LaunchWorkstreamResultDetails };
}

let savedUser: string | undefined;
beforeEach(() => {
	savedUser = process.env.USER;
	process.env.USER = "btimothyhar";
});
afterEach(() => {
	if (savedUser === undefined) delete process.env.USER;
	else process.env.USER = savedUser;
});
