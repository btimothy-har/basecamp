import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { WorkspaceState, WorkspaceWorktree } from "pi-core/platform/workspace.ts";
import type { WorktreeResult } from "pi-core/workspace/worktree.ts";
import type { DaemonClient, WorkstreamDetail, WorkstreamSummary } from "../../agents/daemon/client.ts";
import type { HerdrWorkstreamOpenResult } from "../herdr.ts";
import {
	executeLaunchWorkstream,
	executeListWorkstreams,
	executeSetWorkstreamStatus,
	type LaunchWorkstreamResultDetails,
	type ListWorkstreamsResultDetails,
	type SetWorkstreamStatusResultDetails,
	type WorkstreamToolsDeps,
} from "../tools.ts";

function makeWorkstreamDetail(overrides: Partial<WorkstreamDetail> = {}): WorkstreamDetail {
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

function makeWorkstreamSummary(overrides: Partial<WorkstreamSummary> = {}): WorkstreamSummary {
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

class FakeDaemonClient {
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

function makeWorkspace(overrides: Partial<WorkspaceState> = {}): WorkspaceState {
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

function baseParams(overrides: Record<string, unknown> = {}) {
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

function makeDeps(client: FakeDaemonClient, overrides: Partial<WorkstreamToolsDeps> = {}) {
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

async function runLaunch(params: unknown, deps: WorkstreamToolsDeps) {
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

describe("launch_workstream validation", () => {
	it("validates non-empty required input at the execution boundary", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { result, details } = await runLaunch(baseParams({ source: { dossierPath: " " } }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /source\.dossierPath/);
		assert.equal(client.createCalls.length, 0);
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });
		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("fails when no repo workspace is available", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(makeWorkspace({ repo: null }));
		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /current git repository/);
		assert.equal(client.createCalls.length, 0);
	});
});

describe("launch_workstream CREATE path", () => {
	it("creates a workstream with a unique slug and provisions the worktree", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "steady-amber-otter");
		assert.equal(harness.provisionCalls.length, 1);
		assert.equal(harness.provisionCalls[0]?.label, "copilot/steady-amber-otter");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/launch-workstream-too");
		assert.equal(details.worktree?.label, "copilot/steady-amber-otter");
		assert.match(details.next_step, /pi --workstream=/);
		assert.equal(client.createCalls.length, 1);
		assert.equal(client.createCalls[0]?.slug, "steady-amber-otter");
		assert.equal(client.createCalls[0]?.label, "Launch Workstream Too");
		assert.equal(client.createCalls[0]?.sourceDossierPath, "/graph/pages/Dossier.md");
	});

	it("regenerates slug on slug_conflict and retries the create", async () => {
		const client = new FakeDaemonClient({ createStatus: "slug_conflict" });
		const harness = makeDeps(client);

		// First call returns slug_conflict, then we flip to created on retry
		let callCount = 0;
		const originalCreate = client.createWorkstream.bind(client);
		client.createWorkstream = async (input) => {
			callCount += 1;
			if (callCount === 1) {
				client.createCalls.push(input);
				return { status: "slug_conflict", workstream_id: null, slug: null, error: "slug taken" };
			}
			return originalCreate(input);
		};
		client.setOpts({ createStatus: "created" });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "calm-cedar-heron");
		assert.ok(callCount >= 2, "should have retried create");
	});

	it("regenerates slug when the generated slug already exists in the daemon", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamDetail("steady-amber-otter", makeWorkstreamDetail());

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "calm-cedar-heron");
		assert.equal(client.createCalls[0]?.slug, "calm-cedar-heron");
	});

	it("fails when the derived branch is already checked out", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setListedWorktrees([
			{
				kind: "git-worktree",
				label: "other-wt",
				path: "/worktrees/existing",
				branch: "bt/launch-workstream-too",
				created: false,
			} as WorkspaceWorktree,
		]);

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /branch bt\/launch-workstream-too is already checked out/);
		assert.equal(client.createCalls.length, 0);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("fails when worktree provisioning throws", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setProvision(async () => {
			throw new Error("cannot create branch");
		});

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /cannot create branch/);
		assert.equal(client.createCalls.length, 0);
	});

	it("returns transient setup and herdr summaries inline, not persisted", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setSetupCommand("make setup");
		harness.setHerdrResult({ status: "opened", message: "opened", args: [] });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.ok(details.setup_summary);
		assert.ok(details.herdr_summary);
		assert.equal(harness.setupCalls.length, 1);
		assert.equal(harness.herdrCalls.length, 1);
		// No persistence calls beyond createWorkstream
		assert.equal(client.attachCalls.length, 0);
		assert.equal(client.updateCalls.length, 0);
	});

	it("uses worktreeSlug for the bt/ branch name", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { details } = await runLaunch(
			baseParams({ workstream: { label: "Ignored Label", brief: "Brief.", worktreeSlug: "feature-launch" } }),
			harness.deps,
		);

		assert.equal(details.status, "launched");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/feature-launch");
		assert.equal(details.worktree?.branch, "bt/feature-launch");
	});
});

describe("launch_workstream CARRY path", () => {
	it("resolves an existing workstream and reuses the worktree without creating a new workstream", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const existing = makeWorkstreamDetail({ slug: "existing-slug", id: "ws-existing", label: "Existing" });
		harness.setWorkstreamDetail("existing-slug", existing);

		const { details } = await runLaunch(baseParams({ workstream_id: "existing-slug" }), harness.deps);

		assert.equal(details.status, "carried");
		assert.equal(details.slug, "existing-slug");
		assert.equal(details.id, "ws-existing");
		assert.equal(harness.provisionCalls.length, 1);
		assert.equal(harness.provisionCalls[0]?.label, "copilot/existing-slug");
		assert.equal(client.createCalls.length, 0, "should not call createWorkstream on carry");
	});

	it("fails when the carry identifier does not resolve", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		const { result, details } = await runLaunch(baseParams({ workstream_id: "nonexistent" }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /No workstream found/);
		assert.equal(client.createCalls.length, 0);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("provisions the worktree idempotently (reuses if present)", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const existing = makeWorkstreamDetail({ slug: "carry-slug", id: "ws-carry" });
		harness.setWorkstreamDetail("carry-slug", existing);
		harness.setCreated(false);

		const { details } = await runLaunch(baseParams({ workstream_id: "carry-slug" }), harness.deps);

		assert.equal(details.status, "carried");
		assert.equal(details.worktree?.created, false);
	});
});

describe("list_workstreams", () => {
	it("lists workstreams from the daemon with filters", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamSummaries([
			makeWorkstreamSummary({ slug: "alpha", label: "Alpha" }),
			makeWorkstreamSummary({ slug: "beta", label: "Beta" }),
		]);

		const result = await executeListWorkstreams({ status: "open" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 2);
		assert.equal(details.workstreams[0]?.slug, "alpha");
		assert.equal(details.workstreams[1]?.slug, "beta");
	});

	it("returns the detail with agents view for a single-identifier query", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const detail = makeWorkstreamDetail({
			slug: "alpha",
			agents: [
				{
					agent_id: "agent-1",
					agent_handle: "quiet-badger-3dc",
					repo: "org/repo",
					worktree_label: "copilot/alpha",
					status: "attached",
					error: null,
					joined_at: "2026-07-03T00:00:00.000Z",
					run_status: "running",
				},
			],
		});
		harness.setWorkstreamDetail("alpha", detail);

		const result = await executeListWorkstreams({ query: "alpha" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 1);
		assert.ok(details.workstream);
		assert.equal(details.workstream.agents.length, 1);
		assert.equal(details.workstream.agents[0]?.agent_handle, "quiet-badger-3dc");
		assert.match(details.next_step, /quiet-badger-3dc/);
	});

	it("falls through to list when single query does not match a detail", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamSummaries([makeWorkstreamSummary({ slug: "alpha" })]);

		const result = await executeListWorkstreams({ query: "nonexistent" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 1);
		assert.equal(details.workstream, undefined);
	});

	it("fails when the daemon returns null (not connected)", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client, { listWorkstreamSummaries: async () => null });

		const result = await executeListWorkstreams({}, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("passes repo, dossierPath, and status filters through", async () => {
		const client = new FakeDaemonClient();
		let capturedFilter: Record<string, unknown> = {};
		const harness = makeDeps(client, {
			listWorkstreamSummaries: async (_sp, filter) => {
				capturedFilter = filter;
				return [];
			},
		});

		await executeListWorkstreams({ repo: "org/repo", dossierPath: "/d.md", status: "closed" }, harness.deps);

		assert.deepEqual(capturedFilter, { repo: "org/repo", dossierPath: "/d.md", status: "closed" });
	});
});

describe("set_workstream_status", () => {
	it("updates status to open", async () => {
		const client = new FakeDaemonClient({ updateStatus: "updated" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(details.status, "updated");
		assert.match(details.message, /now open/);
		assert.equal(client.updateCalls.length, 1);
		assert.equal(client.updateCalls[0]?.workstream, "alpha");
		assert.equal(client.updateCalls[0]?.status, "open");
	});

	it("updates status to closed", async () => {
		const client = new FakeDaemonClient({ updateStatus: "updated" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "beta", status: "closed" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(details.status, "updated");
		assert.match(details.message, /now closed/);
		assert.equal(client.updateCalls[0]?.status, "closed");
	});

	it("returns not_found when the workstream does not exist", async () => {
		const client = new FakeDaemonClient({ updateStatus: "not_found" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "nope", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "not_found");
		assert.match(details.message, /No workstream found/);
	});

	it("returns invalid_status for an invalid status", async () => {
		const client = new FakeDaemonClient({ updateStatus: "invalid_status" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "invalid_status");
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("validates required params", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /requires a non-empty workstream/);
		assert.equal(client.updateCalls.length, 0);
	});
});
