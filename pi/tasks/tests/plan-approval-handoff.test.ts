import assert from "node:assert/strict";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resetAgentMode, setAgentMode } from "#core/agent-mode/index.ts";
import { registerWorkspaceRuntime, resetWorkspaceRuntimeForTesting } from "#core/project/workspace/runtime.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import type { PlanDraft } from "#tasks/schemas/plan.ts";
import { SECTION_NAMES } from "#tasks/schemas/plan.ts";
import { type PlanAccess, type PlanDeps, registerPlan } from "#tasks/tools/plan-tool.ts";
import type { HandoffOutcome } from "#tasks/workflows/handoff/index.ts";

interface PlanParams {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
	worktreeSlug?: string;
	tasks: Array<{ label: string; description: string; criteria: string }>;
}

interface RegisteredTool {
	name: string;
	execute(
		toolCallId: string,
		params: PlanParams,
		signal: AbortSignal | undefined,
		onUpdate: unknown,
		ctx: ExtensionContext,
	): Promise<{ content: { type: string; text: string }[] }>;
}

type AgentEndHandler = (event: unknown, ctx: ExtensionContext) => Promise<void>;

class FakePi {
	readonly userMessages: string[] = [];
	readonly events = { emit: () => {}, on: () => () => {} };
	private tool: RegisteredTool | null = null;
	private agentEnd: AgentEndHandler | null = null;

	on(event: string, handler: AgentEndHandler): void {
		if (event === "agent_end") this.agentEnd = handler;
	}

	registerTool(tool: RegisteredTool): void {
		this.tool = tool;
	}

	sendUserMessage(content: string): void {
		this.userMessages.push(content);
	}

	getPlan(): RegisteredTool {
		assert.ok(this.tool, "plan tool should be registered");
		return this.tool;
	}

	async fireAgentEnd(ctx: ExtensionContext): Promise<void> {
		assert.ok(this.agentEnd, "agent_end handler should be registered");
		await this.agentEnd(undefined, ctx);
	}

	async exec(_command: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
		const invocation = args.join(" ");
		if (invocation === "rev-parse --show-toplevel") return { code: 0, stdout: "/repo\n", stderr: "" };
		if (invocation === "rev-parse --git-dir --git-common-dir") {
			return { code: 0, stdout: ".git\n.git\n", stderr: "" };
		}
		if (invocation === "-C /repo remote get-url origin") return { code: 1, stdout: "", stderr: "no remote" };
		if (invocation === "-C /repo worktree list --porcelain") {
			return { code: 0, stdout: "worktree /repo\nbranch refs/heads/main\n", stderr: "" };
		}
		throw new Error(`Unexpected git invocation: ${invocation}`);
	}
}

// buildPendingImplementationHandoff reads the repo out of workspace state, so the
// approval path needs a real runtime behind a fake git.
async function initializeWorkspace(t: TestContext, pi: FakePi): Promise<void> {
	resetWorkspaceRuntimeForTesting();
	t.after(resetWorkspaceRuntimeForTesting);
	const service = registerWorkspaceRuntime(pi as unknown as ExtensionAPI);
	await service.initialize({
		launchCwd: "/repo",
		unsafeEditFlag: false,
		unsafeEditConstraints: { readOnly: false, hasUI: true, isSubagent: false, sandboxed: false },
	});
}

const params: PlanParams = {
	goal: "Add the continuation guard",
	context: "Agents stop mid-work.",
	design: "Judge the stop against a rubric.",
	success: "Premature stops are nudged.",
	boundaries: "No daemon changes.",
	worktreeSlug: "continuation-guard",
	tasks: [{ label: "Implement", description: "Add the hook", criteria: "Tests pass" }],
};

const readyOutcome: HandoffOutcome = {
	status: "ready",
	worktree: {
		worktreeDir: "/tmp/worktrees/wt/continuation-guard",
		label: "wt/continuation-guard",
		branch: "bt/continuation-guard",
		created: true,
	},
	setupSummary: undefined,
};

function tasksRuntime(): TasksRuntime {
	return {
		state: { goal: null, tasks: [] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget() {},
		persistState() {},
	} as unknown as TasksRuntime;
}

/** The overlay is what records approvals, so an approving fake has to mark the draft. */
function approveEverything(draft: PlanDraft): void {
	for (const name of SECTION_NAMES) draft[name].review = { approved: true, feedback: null };
	draft.tasksReview = { approved: true, feedback: null };
}

function setup(overrides: Partial<PlanDeps> = {}): { pi: FakePi; tool: RegisteredTool; plan: PlanAccess } {
	const pi = new FakePi();
	const plan = registerPlan(pi as unknown as ExtensionAPI, tasksRuntime(), {
		// Pinned so the suite is deterministic even when run inside a dispatched agent.
		isSubagent: () => false,
		review: async (draft) => {
			approveEverything(draft);
			return "submit";
		},
		handoff: async () => readyOutcome,
		...overrides,
	});
	return { pi, tool: pi.getPlan(), plan };
}

function uiContext(usagePercent: number | null = 0): ExtensionContext {
	return {
		hasUI: true,
		ui: { custom: async () => "submit" },
		getContextUsage: () => ({ percent: usagePercent }),
		compact: () => {},
	} as unknown as ExtensionContext;
}

async function approve(tool: RegisteredTool, ctx: ExtensionContext): Promise<string> {
	setAgentMode("work");
	const result = await tool.execute("call-1", params, undefined, undefined, ctx);
	return result.content[0]?.text ?? "";
}

describe("plan approval arms and releases the handoff latch", () => {
	it("arms at approval and releases once the handoff prompt is sent", async (t) => {
		t.after(() => resetAgentMode());
		const { pi, tool, plan } = setup();
		await initializeWorkspace(t, pi);
		const ctx = uiContext();

		assert.equal(plan.isHandoffActive(), false);

		const text = await approve(tool, ctx);
		assert.match(text, /implementation/);
		assert.equal(plan.isHandoffActive(), true, "the restart is owed from the moment the plan is approved");

		await pi.fireAgentEnd(ctx);
		// The handoff defers to the next macrotask so Pi can clear its streaming state.
		assert.equal(plan.isHandoffActive(), true, "still owed across the macrotask boundary");
		await new Promise((resolve) => setTimeout(resolve, 0));

		assert.equal(pi.userMessages.length, 1);
		assert.equal(plan.isHandoffActive(), false, "released only once the prompt is actually sent");
	});

	it("stays armed for the whole compaction pass", async (t) => {
		t.after(() => resetAgentMode());
		const { pi, tool, plan } = setup();
		await initializeWorkspace(t, pi);
		let onComplete: (() => void) | null = null;
		const ctx = {
			hasUI: true,
			ui: { custom: async () => "submit" },
			// Over the threshold, so the handoff compacts before sending.
			getContextUsage: () => ({ percent: 90 }),
			compact: (request: { onComplete: () => void }) => {
				onComplete = request.onComplete;
			},
		} as unknown as ExtensionContext;

		await approve(tool, ctx);
		await pi.fireAgentEnd(ctx);
		await new Promise((resolve) => setTimeout(resolve, 0));

		assert.ok(onComplete, "compaction should have been requested");
		assert.deepEqual(pi.userMessages, [], "nothing is sent until compaction reports");
		assert.equal(plan.isHandoffActive(), true, "a peer must still see the restart in flight");

		(onComplete as unknown as () => void)();
		assert.equal(pi.userMessages.length, 1);
		assert.equal(plan.isHandoffActive(), false);
	});

	it("never arms when the worktree handoff is cancelled", async (t) => {
		t.after(() => resetAgentMode());
		const { pi, tool, plan } = setup({ handoff: async () => ({ status: "cancelled" }) });
		await initializeWorkspace(t, pi);
		const ctx = uiContext();

		const text = await approve(tool, ctx);

		assert.match(text, /handoff_cancelled/);
		assert.equal(plan.isHandoffActive(), false);
		await pi.fireAgentEnd(ctx);
		await new Promise((resolve) => setTimeout(resolve, 0));
		assert.deepEqual(pi.userMessages, [], "no handoff was scheduled");
	});

	it("never arms for an approved analysis plan", async (t) => {
		t.after(() => resetAgentMode());
		const { pi, tool, plan } = setup();
		await initializeWorkspace(t, pi);
		const ctx = uiContext();

		setAgentMode("analysis");
		await tool.execute("call-1", params, undefined, undefined, ctx);

		assert.equal(plan.isHandoffActive(), false);
		await pi.fireAgentEnd(ctx);
		await new Promise((resolve) => setTimeout(resolve, 0));
		assert.deepEqual(pi.userMessages, []);
	});
});
