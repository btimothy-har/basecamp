import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { TasksRuntime } from "#tasks/lifecycle/index.ts";
import { type PlanAccess, registerPlan } from "#tasks/tools/plan-tool.ts";

interface PlanParams {
	goal: string;
	context: string;
	design: string;
	success: string;
	boundaries: string;
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
}

const params: PlanParams = {
	goal: "Add the continuation guard",
	context: "Agents stop mid-work.",
	design: "Judge the stop against a rubric.",
	success: "Premature stops are nudged.",
	boundaries: "No daemon changes.",
	tasks: [{ label: "Implement", description: "Add the hook", criteria: "Tests pass" }],
};

function tasksRuntime(): TasksRuntime {
	return {
		state: { goal: null, tasks: [] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget() {},
		persistState() {},
	};
}

function register(): { pi: FakePi; tool: RegisteredTool; plan: PlanAccess } {
	const pi = new FakePi();
	// Pinned so the suite is deterministic even when run inside a dispatched agent.
	const plan = registerPlan(pi as unknown as ExtensionAPI, tasksRuntime(), { isSubagent: () => false });
	return { pi, tool: pi.getPlan(), plan };
}

const noUiContext = { hasUI: false } as unknown as ExtensionContext;

describe("PlanAccess.isHandoffActive", () => {
	it("is inactive before any plan is submitted", () => {
		const { plan } = register();
		assert.equal(plan.isHandoffActive(), false);
	});

	it("stays inactive when a plan returns feedback rather than an approval", async () => {
		const { tool, plan } = register();

		const result = await tool.execute("call-1", params, undefined, undefined, noUiContext);

		assert.equal(JSON.parse(result.content[0]?.text ?? "{}").status, "feedback");
		assert.equal(plan.isHandoffActive(), false);
	});

	it("stays inactive when a plan review is declined", async () => {
		const { tool, plan } = register();
		const ctx = { hasUI: true, ui: { custom: async () => "decline" } } as unknown as ExtensionContext;

		const result = await tool.execute("call-1", params, undefined, undefined, ctx);

		assert.equal(JSON.parse(result.content[0]?.text ?? "{}").status, "declined");
		assert.equal(plan.isHandoffActive(), false);
	});

	// A stop with nothing scheduled must not look like a restart in flight, or the
	// continuation guard would suppress itself on every ordinary turn.
	it("stays inactive and sends nothing when a run ends with no handoff scheduled", async () => {
		const { pi, plan } = register();

		await pi.fireAgentEnd(noUiContext);

		assert.equal(plan.isHandoffActive(), false);
		assert.deepEqual(pi.userMessages, []);
	});
});
