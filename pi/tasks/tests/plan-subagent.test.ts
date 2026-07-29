import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getAgentMode, resetAgentMode, setAgentMode } from "#core/agent-mode/index.ts";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import { type PlanAccess, type PlanDeps, registerPlan } from "#tasks/tools/plan-tool.ts";

interface PlanParams {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
	worktreeSlug?: string;
	tasks: Array<{ label: string; description: string; criteria: string }>;
}

interface ToolResult {
	content: { type: string; text: string }[];
}

interface RegisteredTool {
	name: string;
	description: string;
	execute(
		toolCallId: string,
		params: PlanParams,
		signal: AbortSignal | undefined,
		onUpdate: unknown,
		ctx: ExtensionContext,
	): Promise<ToolResult>;
}

class FakePi {
	readonly events = { emit: () => {}, on: () => () => {} };
	private tool: RegisteredTool | null = null;

	on(): void {}

	registerTool(tool: RegisteredTool): void {
		this.tool = tool;
	}

	getPlan(): RegisteredTool {
		assert.ok(this.tool, "plan tool should be registered");
		return this.tool;
	}
}

const params: PlanParams = {
	goal: "Refactor the widget pipeline",
	context: "The pipeline mixes parsing and rendering.",
	design: "Split parse and render stages.",
	success: "Stages are independently testable.",
	boundaries: "No new output formats.",
	tasks: [
		{ label: "Extract parser", description: "Move parsing out", criteria: "Parser has its own tests" },
		{ label: "Extract renderer", description: "Move rendering out", criteria: "Renderer has its own tests" },
	],
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

function setup(deps: Partial<PlanDeps> = {}): {
	tool: RegisteredTool;
	plan: PlanAccess;
	runtime: TasksRuntime;
	handoffCalls: number;
	countHandoffs: () => number;
} {
	const pi = new FakePi();
	const runtime = tasksRuntime();
	let handoffCalls = 0;
	const plan = registerPlan(pi as unknown as ExtensionAPI, runtime, {
		isSubagent: () => true,
		handoff: (async () => {
			handoffCalls++;
			throw new Error("handoff must not run for a subagent plan");
		}) as PlanDeps["handoff"],
		...deps,
	});
	return { tool: pi.getPlan(), plan, runtime, handoffCalls, countHandoffs: () => handoffCalls };
}

const headlessContext = { hasUI: false } as unknown as ExtensionContext;

afterEach(() => {
	resetAgentMode();
});

describe("subagent plan auto-approval", () => {
	it("approves in one call and executes in place", async () => {
		const { tool, runtime, countHandoffs } = setup();

		const result = await tool.execute("call-1", params, undefined, undefined, headlessContext);
		const parsed = JSON.parse(result.content[0]?.text ?? "{}");

		assert.equal(parsed.status, "approved");
		assert.equal(parsed.plan_mode, "implementation");
		assert.match(parsed.next_step, /current workspace/);
		assert.equal(parsed.worktree, undefined);
		assert.equal(parsed.handoff_status, undefined);
		assert.equal(countHandoffs(), 0);
		assert.equal(runtime.state.goal, params.goal);
		assert.deepEqual(
			runtime.state.tasks.map((t) => ({ label: t.label, status: t.status })),
			[
				{ label: "Extract parser", status: "pending" },
				{ label: "Extract renderer", status: "pending" },
			],
		);
		assert.equal(getAgentMode(), "work");
	});

	it("never arms the implementation handoff latch", async () => {
		const { tool, plan } = setup();

		await tool.execute("call-1", params, undefined, undefined, headlessContext);

		assert.equal(plan.isHandoffActive(), false);
	});

	it("skips the review overlay even when a UI is present", async () => {
		let reviewCalls = 0;
		const { tool } = setup({
			review: async () => {
				reviewCalls++;
				return "decline";
			},
		});
		const uiContext = { hasUI: true } as unknown as ExtensionContext;

		const result = await tool.execute("call-1", params, undefined, undefined, uiContext);

		assert.equal(reviewCalls, 0);
		assert.equal(JSON.parse(result.content[0]?.text ?? "{}").status, "approved");
	});

	it("keeps analysis-mode approvals in analysis mode", async () => {
		setAgentMode("analysis");
		const { tool, runtime, countHandoffs } = setup();

		const result = await tool.execute("call-1", params, undefined, undefined, headlessContext);
		const parsed = JSON.parse(result.content[0]?.text ?? "{}");

		assert.equal(parsed.status, "approved");
		assert.equal(parsed.plan_mode, "analysis");
		assert.equal(countHandoffs(), 0);
		assert.equal(runtime.state.goal, params.goal);
		assert.equal(getAgentMode(), "analysis");
	});

	it("describes the auto-approving contract in the tool description", () => {
		const { tool } = setup();
		assert.match(tool.description, /auto-approved/);
		assert.match(tool.description, /current workspace/);
	});

	it("primary headless sessions still receive feedback, not auto-approval", async () => {
		const pi = new FakePi();
		registerPlan(pi as unknown as ExtensionAPI, tasksRuntime(), { isSubagent: () => false });
		const tool = pi.getPlan();

		const result = await tool.execute("call-1", params, undefined, undefined, headlessContext);
		const parsed = JSON.parse(result.content[0]?.text ?? "{}");

		assert.equal(parsed.status, "feedback");
		assert.deepEqual(Object.values(parsed.approved), [null, null, null, null, null, null]);
	});
});
