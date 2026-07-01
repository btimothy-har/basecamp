import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentLauncher } from "pi-core/platform/agent-launcher.ts";
import type { WorkspaceState } from "pi-core/platform/workspace.ts";
import { resetAgentMode, setAgentMode } from "pi-core/session/agent-mode.ts";
import { buildApprovedWorkstreamResult, registerPlan } from "../planning/plan.ts";
import { type PlanDraft, SECTION_NAMES, type WorkstreamPlanDraft } from "../planning/review.ts";
import type { GoalCycle, Task, TasksAccess } from "../tasks/tasks.ts";

interface RegisteredTool {
	name: string;
	execute(
		toolCallId: string,
		params: Record<string, unknown>,
		signal: AbortSignal,
		onUpdate: () => void,
		ctx: ExtensionContext,
	): Promise<{ content: { type: "text"; text: string }[]; details?: unknown }>;
}

class FakePi {
	readonly tools = new Map<string, RegisteredTool>();

	on(): void {}

	registerTool(tool: RegisteredTool): void {
		this.tools.set(tool.name, tool);
	}
}

class FakeTasksAccess implements TasksAccess {
	activated: { goal: string; tasks: Task[]; planRef: GoalCycle["planRef"] } | null = null;

	getState() {
		return { goal: null, tasks: [] };
	}

	setNotes(): void {}

	activateGoalCycle(goal: string, tasks: Task[], planRef: GoalCycle["planRef"]): void {
		this.activated = { goal, tasks, planRef };
	}

	getPlanRef(): GoalCycle["planRef"] {
		return null;
	}

	getContext(): ExtensionContext | null {
		return null;
	}
}

function createContext(): ExtensionContext {
	return {
		hasUI: false,
		sessionManager: { getSessionId: () => "plan-execution-test" },
	} as unknown as ExtensionContext;
}

function planTool(pi: FakePi): RegisteredTool {
	const tool = pi.tools.get("plan");
	assert.ok(tool, "plan tool should be registered");
	return tool;
}

function approveDraft(draft: PlanDraft): void {
	for (const section of SECTION_NAMES) {
		draft[section].review = { approved: true, feedback: null };
	}
	if (draft.executionKind === "tasks") {
		draft.tasksReview = { approved: true, feedback: null };
	} else {
		draft.workstreamsReview = { approved: true, feedback: null };
	}
}

function approvedWorkstreamDraft(workstreams: WorkstreamPlanDraft["workstreams"]): WorkstreamPlanDraft {
	return {
		goal: { content: "Program goal", review: { approved: true, feedback: null } },
		context: { content: "Context", review: { approved: true, feedback: null } },
		design: { content: "Design", review: { approved: true, feedback: null } },
		success: { content: "Success", review: { approved: true, feedback: null } },
		boundaries: { content: "Boundaries", review: { approved: true, feedback: null } },
		executionKind: "workstreams",
		workstreams,
		workstreamsReview: { approved: true, feedback: null },
	};
}

function parseWorkstreamResult(text: string): Record<string, any> {
	return JSON.parse(text) as Record<string, any>;
}

function piStub(): ExtensionAPI {
	return {} as unknown as ExtensionAPI;
}

function contextWithSession(sessionId: string): ExtensionContext {
	return {
		hasUI: false,
		sessionManager: { getSessionId: () => sessionId },
	} as unknown as ExtensionContext;
}

function workspaceState(activeWorktree: WorkspaceState["activeWorktree"] = null): WorkspaceState {
	return {
		launchCwd: "/repo",
		effectiveCwd: activeWorktree?.path ?? "/repo",
		scratchDir: "/scratch",
		repo: { isRepo: true, name: "org/repo", root: "/repo", remoteUrl: "git@example.com:org/repo.git" },
		protectedRoot: "/repo",
		activeWorktree,
		unsafeEdit: false,
	};
}

function successfulLauncher(calls: Parameters<AgentLauncher["launch"]>[0][] = []): AgentLauncher {
	return {
		id: "test-launcher",
		async launch(input) {
			calls.push(input);
			return { ok: true, agentHandle: `worker-${calls.length}`, agent: input.agent ?? "ad-hoc" };
		},
	};
}

async function executeText(tool: RegisteredTool, params: Record<string, unknown>): Promise<string> {
	const result = await tool.execute("1", params, new AbortController().signal, () => {}, createContext());
	const first = result.content[0];
	assert.equal(first?.type, "text");
	return first.text;
}

const ORIGINAL_USER = process.env.USER;
const ORIGINAL_BASECAMP_REPO_ROOT = process.env.BASECAMP_REPO_ROOT;

describe("plan execution result shapes", () => {
	afterEach(() => {
		resetAgentMode();
		if (ORIGINAL_USER === undefined) delete process.env.USER;
		else process.env.USER = ORIGINAL_USER;
		if (ORIGINAL_BASECAMP_REPO_ROOT === undefined) delete process.env.BASECAMP_REPO_ROOT;
		else process.env.BASECAMP_REPO_ROOT = ORIGINAL_BASECAMP_REPO_ROOT;
	});

	it("preserves the approved task-plan result shape", async () => {
		setAgentMode("analysis");
		const pi = new FakePi();
		const tasksAccess = new FakeTasksAccess();
		const access = registerPlan(pi as unknown as ExtensionAPI, tasksAccess);
		const tool = planTool(pi);
		const params = {
			goal: "Task goal",
			context: "Context",
			design: "Design",
			success: "Success",
			boundaries: "Boundaries",
			tasks: [{ label: "Task", description: "Do it", criteria: "Done" }],
		};

		const feedback = JSON.parse(await executeText(tool, params));
		assert.equal(feedback.status, "feedback");
		assert.deepEqual(feedback.approved, {
			goal: null,
			context: null,
			design: null,
			success: null,
			boundaries: null,
			tasks: null,
		});
		assert.deepEqual(feedback.revisions, {});
		approveDraft(access.getDraft()!);

		const approved = JSON.parse(await executeText(tool, params));

		assert.equal(approved.status, "approved");
		assert.equal(approved.plan_kind, undefined);
		assert.deepEqual(approved.progress, { completed: 0, deleted: 0, total: 1 });
		assert.deepEqual(approved.tasks, { 0: { label: "Task", status: "pending", criteria: "Done" } });
		assert.equal(approved.workstreams, undefined);
		assert.equal(tasksAccess.activated?.goal, "Task goal");
		assert.equal(tasksAccess.activated?.tasks.length, 1);
	});

	it("returns a clear cancellation result for approved workstream plans without workspace state", async () => {
		const pi = new FakePi();
		const tasksAccess = new FakeTasksAccess();
		const access = registerPlan(pi as unknown as ExtensionAPI, tasksAccess);
		const tool = planTool(pi);
		const params = {
			goal: "Program goal",
			context: "Context",
			design: "Design",
			success: "Success",
			boundaries: "Boundaries",
			workstreams: [
				{
					id: "core",
					label: "Core",
					scope: "Build core",
					outcome: "Core works",
					boundaries: "No UI",
					worktreeSlug: "core-work",
				},
				{
					id: "ui",
					label: "UI",
					scope: "Build UI",
					outcome: "UI works",
					boundaries: "No core changes",
					dependsOn: ["core"],
				},
				{
					id: "e2e",
					label: "E2E",
					scope: "Test the full path",
					outcome: "E2E coverage passes",
					boundaries: "No feature code",
					dependsOn: ["ui"],
				},
			],
		};

		const feedback = JSON.parse(await executeText(tool, params));
		assert.equal(feedback.status, "feedback");
		assert.equal(feedback.plan_kind, "workstreams");
		assert.deepEqual(feedback.approved, {
			goal: null,
			context: null,
			design: null,
			success: null,
			boundaries: null,
			workstreams: null,
		});
		assert.deepEqual(feedback.revisions, {});
		approveDraft(access.getDraft()!);

		const approved = JSON.parse(await executeText(tool, params));

		assert.equal(approved.status, "handoff_cancelled");
		assert.equal(approved.plan_kind, "workstreams");
		assert.equal(approved.implementation_mode, "supervisor");
		assert.equal(approved.handoff_status, "workstream_activation_cancelled");
		assert.match(approved.message, /requires an initialized git repository workspace/);
		assert.deepEqual(approved.workstream_progress, {
			ready: 1,
			blocked: 2,
			activated: 0,
			dispatched: 0,
			failed: 1,
			total: 3,
		});
		assert.deepEqual(approved.workstream_graph, { ready: ["core"], blocked: { ui: ["core"], e2e: ["ui"] } });
		assert.equal(approved.workstreams.core.status, "ready");
		assert.equal(approved.workstreams.core.activation_status, "failed");
		assert.equal(approved.workstreams.core.failure_stage, "worktree");
		assert.equal(approved.workstreams.core.worktreeSlug, "core-work");
		assert.equal(approved.workstreams.ui.status, "blocked");
		assert.equal(approved.workstreams.ui.worktreeSlug, undefined);
		assert.equal(approved.workstreams.e2e.status, "blocked");
		assert.equal(approved.tasks, undefined);
		assert.equal(tasksAccess.activated, null);
	});

	it("records all-blocked workstream plans without provisioning", async () => {
		const draft = approvedWorkstreamDraft([
			{
				id: "core",
				label: "Core",
				scope: "Build core",
				outcome: "Core works",
				boundaries: "No UI",
				dependsOn: ["ui"],
			},
			{
				id: "ui",
				label: "UI",
				scope: "Build UI",
				outcome: "UI works",
				boundaries: "No core changes",
				dependsOn: ["core"],
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-0000"), {
				getWorkspaceState: () => {
					throw new Error("workspace should not be required when no workstreams are ready");
				},
				getAgentLauncher: () => {
					throw new Error("launcher should not be required when no workstreams are ready");
				},
				getOrCreateWorktree: async () => {
					throw new Error("worktree provisioning should not run when no workstreams are ready");
				},
				readWorktreeSetupCommand: () => {
					throw new Error("setup lookup should not run when no workstreams are ready");
				},
				runWorktreeSetup: async () => {
					throw new Error("setup should not run when no workstreams are ready");
				},
			}),
		);

		assert.equal(result.status, "approved");
		assert.equal(result.handoff_status, "workstreams_blocked");
		assert.deepEqual(result.workstream_progress, {
			ready: 0,
			blocked: 2,
			activated: 0,
			dispatched: 0,
			failed: 0,
			total: 2,
		});
		assert.deepEqual(result.workstream_graph, { ready: [], blocked: { core: ["ui"], ui: ["core"] } });
		assert.equal(result.workstreams.core.status, "blocked");
		assert.equal(result.workstreams.core.activation_status, undefined);
		assert.equal(result.workstreams.core.worktree, undefined);
		assert.equal(result.workstreams.ui.status, "blocked");
	});

	it("provisions and launches ready workstreams with derived worktree context", async () => {
		process.env.USER = "Test User";
		const createdCalls: { label: string; branchName: string | null | undefined }[] = [];
		const launchCalls: Parameters<AgentLauncher["launch"]>[0][] = [];
		const draft = approvedWorkstreamDraft([
			{
				id: "core",
				label: "Core",
				scope: "Build core",
				outcome: "Core works",
				boundaries: "No UI",
				worktreeSlug: "core-work",
			},
			{
				id: "api",
				label: "API Package",
				scope: "Build API",
				outcome: "API works",
				boundaries: "No UI",
			},
			{
				id: "ui",
				label: "UI",
				scope: "Build UI",
				outcome: "UI works",
				boundaries: "No core changes",
				dependsOn: ["core"],
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-1234"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => successfulLauncher(launchCalls),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => {
					createdCalls.push({ label, branchName });
					return { worktreeDir: `/worktrees/${label}`, label, branch: branchName ?? "detached", created: true };
				},
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(result.status, "approved");
		assert.equal(result.handoff_status, "workstreams_dispatched");
		assert.deepEqual(result.workstream_graph, { ready: ["core", "api"], blocked: { ui: ["core"] } });
		assert.deepEqual(result.workstream_progress, {
			ready: 2,
			blocked: 1,
			activated: 2,
			dispatched: 2,
			failed: 0,
			total: 3,
		});
		assert.deepEqual(createdCalls, [
			{ label: "wt-te/1234-core-work", branchName: "te/1234-core-work" },
			{ label: "wt-te/1234-api", branchName: "te/1234-api" },
		]);
		assert.deepEqual(result.workstreams.core.worktree, {
			label: "wt-te/1234-core-work",
			path: "/worktrees/wt-te/1234-core-work",
			branch: "te/1234-core-work",
			created: true,
		});
		assert.equal(result.workstreams.core.activation_status, "activated");
		assert.equal(result.workstreams.core.launch_status, "dispatched");
		assert.deepEqual(result.workstreams.core.agent, { handle: "worker-1", type: "worker" });
		assert.equal(result.workstreams.api.activation_status, "activated");
		assert.equal(result.workstreams.api.launch_status, "dispatched");
		assert.equal(result.workstreams.ui.status, "blocked");
		assert.equal(result.workstreams.ui.activation_status, undefined);
		assert.equal(result.workstreams.ui.launch_status, undefined);
		assert.equal(result.workstreams.ui.worktree, undefined);
		assert.equal(launchCalls.length, 2);
		assert.equal(launchCalls[0]?.agent, "worker");
		assert.match(launchCalls[0]?.task ?? "", /Goal: Program goal/);
		assert.match(launchCalls[0]?.task ?? "", /ID: core/);
		assert.match(launchCalls[0]?.task ?? "", /Work only in the assigned worktree path/);
		assert.match(launchCalls[0]?.task ?? "", /Do not create a GitHub PR unless explicitly asked/);
		assert.equal(launchCalls[0]?.workspace?.activeWorktree?.path, "/worktrees/wt-te/1234-core-work");
		assert.equal(launchCalls[0]?.workspace?.activeWorktree?.label, "wt-te/1234-core-work");
		assert.deepEqual(launchCalls[0]?.env, {
			BASECAMP_REPO: "org/repo",
			BASECAMP_SCRATCH_DIR: "/scratch",
			BASECAMP_WORKTREE_DIR: "/worktrees/wt-te/1234-core-work",
			BASECAMP_WORKTREE_LABEL: "wt-te/1234-core-work",
		});
		assert.equal(launchCalls[0]?.title, "Workstream: Core");
		assert.equal(result.tasks, undefined);
	});

	it("runs setup only for newly created ready worktrees and includes the summary", async () => {
		process.env.USER = "Test User";
		const setupCalls: string[] = [];
		const draft = approvedWorkstreamDraft([
			{
				id: "new",
				label: "New Work",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "existing",
				label: "Existing Work",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-abcd"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => successfulLauncher(),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => ({
					worktreeDir: `/worktrees/${label}`,
					label,
					branch: branchName ?? "detached",
					created: label.includes("new"),
				}),
				readWorktreeSetupCommand: () => "npm install",
				runWorktreeSetup: async (_pi, opts) => {
					setupCalls.push(opts.worktreeDir);
					return { ran: true, exitCode: 0, timedOut: false, stderrTail: "" };
				},
			}),
		);

		assert.deepEqual(setupCalls, ["/worktrees/wt-te/abcd-new"]);
		assert.deepEqual(result.workstreams.new.worktree_setup, { ok: true, exit_code: 0, timed_out: false });
		assert.equal(result.workstreams.existing.worktree_setup, undefined);
		assert.equal(result.workstreams.new.activation_status, "activated");
		assert.equal(result.workstreams.existing.activation_status, "activated");
	});

	it("summarizes setup failures without failing unrelated ready streams", async () => {
		process.env.USER = "Test User";
		const draft = approvedWorkstreamDraft([
			{
				id: "nonzero",
				label: "Nonzero",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "timeout",
				label: "Timeout",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "ok",
				label: "OK",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-9999"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => successfulLauncher(),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => ({
					worktreeDir: `/worktrees/${label}`,
					label,
					branch: branchName ?? "detached",
					created: true,
				}),
				readWorktreeSetupCommand: () => "npm install",
				runWorktreeSetup: async (_pi, opts) => {
					if (opts.worktreeDir.includes("nonzero")) {
						return { ran: true, exitCode: 2, timedOut: false, stderrTail: "install failed" };
					}
					if (opts.worktreeDir.includes("timeout")) {
						return { ran: true, exitCode: 124, timedOut: true, stderrTail: "still running" };
					}
					return { ran: true, exitCode: 0, timedOut: false, stderrTail: "" };
				},
			}),
		);

		assert.equal(result.handoff_status, "workstreams_partially_dispatched");
		assert.deepEqual(result.workstream_progress, {
			ready: 3,
			blocked: 0,
			activated: 1,
			dispatched: 1,
			failed: 2,
			total: 3,
		});
		assert.equal(result.workstreams.nonzero.activation_status, "failed");
		assert.equal(result.workstreams.nonzero.failure_stage, "setup");
		assert.deepEqual(result.workstreams.nonzero.worktree_setup, {
			ok: false,
			exit_code: 2,
			timed_out: false,
			stderr_tail: "install failed",
		});
		assert.equal(result.workstreams.timeout.activation_status, "failed");
		assert.equal(result.workstreams.timeout.message, "Worktree setup timed out.");
		assert.deepEqual(result.workstreams.timeout.worktree_setup, {
			ok: false,
			exit_code: 124,
			timed_out: true,
			stderr_tail: "still running",
		});
		assert.equal(result.workstreams.ok.activation_status, "activated");
	});

	it("isolates worktree creation failures per ready stream", async () => {
		process.env.USER = "Test User";
		const launchCalls: Parameters<AgentLauncher["launch"]>[0][] = [];
		const draft = approvedWorkstreamDraft([
			{
				id: "bad",
				label: "Bad",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "good",
				label: "Good",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-2222"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => successfulLauncher(launchCalls),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => {
					if (label.includes("bad")) throw new Error("git worktree failed");
					return { worktreeDir: `/worktrees/${label}`, label, branch: branchName ?? "detached", created: true };
				},
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.deepEqual(result.workstream_progress, {
			ready: 2,
			blocked: 0,
			activated: 1,
			dispatched: 1,
			failed: 1,
			total: 2,
		});
		assert.equal(result.workstreams.bad.activation_status, "failed");
		assert.equal(result.workstreams.bad.failure_stage, "worktree");
		assert.equal(result.workstreams.bad.message, "git worktree failed");
		assert.equal(result.workstreams.bad.worktree, undefined);
		assert.equal(result.workstreams.good.activation_status, "activated");
		assert.equal(result.workstreams.good.launch_status, "dispatched");
		assert.equal(launchCalls.length, 1);
		assert.match(launchCalls[0]?.task ?? "", /ID: good/);
		assert.deepEqual(result.workstreams.good.worktree, {
			label: "wt-te/2222-good",
			path: "/worktrees/wt-te/2222-good",
			branch: "te/2222-good",
			created: true,
		});
	});

	it("isolates launch failures without failing unrelated dispatched streams", async () => {
		process.env.USER = "Test User";
		const draft = approvedWorkstreamDraft([
			{
				id: "bad",
				label: "Bad Launch",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "good",
				label: "Good Launch",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "blocked",
				label: "Blocked",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
				dependsOn: ["good"],
			},
		]);
		const launchCalls: string[] = [];

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-5555"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => ({
					id: "failing-launcher",
					async launch(input) {
						launchCalls.push(input.workspace?.activeWorktree?.label ?? "missing");
						if (input.task.includes("ID: bad")) {
							return { ok: false, agent: "worker", message: "daemon rejected launch" };
						}
						return { ok: true, agentHandle: "good-handle", agent: "worker" };
					},
				}),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => ({
					worktreeDir: `/worktrees/${label}`,
					label,
					branch: branchName ?? "detached",
					created: true,
				}),
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(result.handoff_status, "workstreams_partially_dispatched");
		assert.deepEqual(result.workstream_progress, {
			ready: 2,
			blocked: 1,
			activated: 2,
			dispatched: 1,
			failed: 1,
			total: 3,
		});
		assert.deepEqual(launchCalls, ["wt-te/5555-bad", "wt-te/5555-good"]);
		assert.equal(result.workstreams.bad.activation_status, "activated");
		assert.equal(result.workstreams.bad.launch_status, "failed");
		assert.equal(result.workstreams.bad.failure_stage, "launch");
		assert.equal(result.workstreams.bad.message, "daemon rejected launch");
		assert.equal(result.workstreams.good.launch_status, "dispatched");
		assert.deepEqual(result.workstreams.good.agent, { handle: "good-handle", type: "worker" });
		assert.equal(result.workstreams.blocked.launch_status, undefined);
	});

	it("isolates thrown launch errors without aborting the approved result", async () => {
		process.env.USER = "Test User";
		const draft = approvedWorkstreamDraft([
			{
				id: "bad",
				label: "Bad Launch",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
			{
				id: "good",
				label: "Good Launch",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-7777"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => ({
					id: "throwing-launcher",
					async launch(input) {
						if (input.task.includes("ID: bad")) throw new Error("daemon unavailable");
						return { ok: true, agentHandle: "good-handle", agent: "worker" };
					},
				}),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => ({
					worktreeDir: `/worktrees/${label}`,
					label,
					branch: branchName ?? "detached",
					created: true,
				}),
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(result.handoff_status, "workstreams_partially_dispatched");
		assert.deepEqual(result.workstream_progress, {
			ready: 2,
			blocked: 0,
			activated: 2,
			dispatched: 1,
			failed: 1,
			total: 2,
		});
		assert.equal(result.workstreams.bad.launch_status, "failed");
		assert.equal(result.workstreams.bad.failure_stage, "launch");
		assert.equal(result.workstreams.bad.message, "daemon unavailable");
		assert.equal(result.workstreams.good.launch_status, "dispatched");
	});

	it("cancels before provisioning when no launcher is registered", async () => {
		process.env.USER = "Test User";
		let createCalls = 0;
		const draft = approvedWorkstreamDraft([
			{
				id: "ready",
				label: "Ready",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-6666"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => null,
				getOrCreateWorktree: async () => {
					createCalls++;
					throw new Error("worktree provisioning should not run without a launcher");
				},
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(createCalls, 0);
		assert.equal(result.status, "handoff_cancelled");
		assert.equal(result.handoff_status, "workstream_launch_cancelled");
		assert.deepEqual(result.workstream_progress, {
			ready: 1,
			blocked: 0,
			activated: 0,
			dispatched: 0,
			failed: 1,
			total: 1,
		});
		assert.equal(result.workstreams.ready.activation_status, undefined);
		assert.equal(result.workstreams.ready.worktree, undefined);
		assert.equal(result.workstreams.ready.launch_status, "failed");
		assert.equal(result.workstreams.ready.failure_stage, "launch");
		assert.equal(result.workstreams.ready.message, "No agent launcher is registered.");
	});

	it("fails duplicate ready worktree labels before provisioning", async () => {
		process.env.USER = "Test User";
		let createCalls = 0;
		const draft = approvedWorkstreamDraft([
			{
				id: "first",
				label: "First",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
				worktreeSlug: "shared",
			},
			{
				id: "second",
				label: "Second",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
				worktreeSlug: "shared",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-4444"), {
				getWorkspaceState: () => workspaceState(),
				getAgentLauncher: () => successfulLauncher(),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => {
					createCalls++;
					return { worktreeDir: `/worktrees/${label}`, label, branch: branchName ?? "detached", created: true };
				},
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(createCalls, 0);
		assert.deepEqual(result.workstream_progress, {
			ready: 2,
			blocked: 0,
			activated: 0,
			dispatched: 0,
			failed: 2,
			total: 2,
		});
		assert.equal(result.handoff_status, "workstreams_failed");
		assert.equal(result.workstreams.first.activation_status, "failed");
		assert.equal(result.workstreams.first.failure_stage, "worktree");
		assert.match(result.workstreams.first.message, /shared by ready workstreams: first, second/);
		assert.equal(result.workstreams.second.activation_status, "failed");
	});

	it("does not mutate coordinator active workspace state or environment", async () => {
		process.env.USER = "Test User";
		process.env.BASECAMP_REPO_ROOT = "coordinator-root";
		const activeWorktree = {
			kind: "git-worktree" as const,
			label: "wt-te/coordinator",
			path: "/worktrees/wt-te/coordinator",
			branch: "te/coordinator",
			created: false,
		};
		const workspace = workspaceState(activeWorktree);
		const draft = approvedWorkstreamDraft([
			{
				id: "ready",
				label: "Ready",
				scope: "Scope",
				outcome: "Outcome",
				boundaries: "Boundaries",
			},
		]);

		const result = parseWorkstreamResult(
			await buildApprovedWorkstreamResult(piStub(), draft, contextWithSession("session-3333"), {
				getWorkspaceState: () => workspace,
				getAgentLauncher: () => successfulLauncher(),
				getOrCreateWorktree: async (_pi, _repoRoot, _repoName, label, branchName) => ({
					worktreeDir: `/worktrees/${label}`,
					label,
					branch: branchName ?? "detached",
					created: true,
				}),
				readWorktreeSetupCommand: () => null,
				runWorktreeSetup: async () => ({ ran: true, exitCode: 0, timedOut: false, stderrTail: "" }),
			}),
		);

		assert.equal(result.workstreams.ready.activation_status, "activated");
		assert.equal(workspace.activeWorktree, activeWorktree);
		assert.equal(process.env.BASECAMP_REPO_ROOT, "coordinator-root");
	});
});
