import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { TasksRuntime } from "../lifecycle/index.ts";
import { registerPlan } from "../tools/plan-tool.ts";

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
	execute(
		toolCallId: string,
		params: PlanParams,
		signal: AbortSignal | undefined,
		onUpdate: unknown,
		ctx: ExtensionContext,
	): Promise<ToolResult>;
}

interface EmittedEvent {
	channel: string;
	data: unknown;
}

class FakePi {
	readonly emitted: EmittedEvent[] = [];
	readonly events = {
		emit: (channel: string, data: unknown) => {
			this.emitted.push({ channel, data });
		},
		on: () => () => {},
	};
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
	goal: "Ship plan review waiting state",
	context: "Plan review blocks on an interactive overlay.",
	design: "Report blocked state around the overlay.",
	success: "The state is balanced on every exit.",
	boundaries: "Do not include worktree selection.",
	tasks: [{ label: "Implement", description: "Add lifecycle events", criteria: "Tests pass" }],
};
const blockedStart: EmittedEvent = {
	channel: "herdr:blocked",
	data: { active: true, label: "Waiting for plan approval" },
};
const blockedEnd: EmittedEvent = { channel: "herdr:blocked", data: { active: false } };

function tasksRuntime(): TasksRuntime {
	return {
		state: { goal: null, tasks: [] },
		cycles: [],
		guardBlockCount: 0,
		updateWidget() {},
		persistState() {},
	};
}

function register(): { pi: FakePi; tool: RegisteredTool } {
	const pi = new FakePi();
	registerPlan(pi as unknown as ExtensionAPI, tasksRuntime());
	return { pi, tool: pi.getPlan() };
}

function contextWithReview(review: () => Promise<"submit" | "decline">): ExtensionContext {
	return { hasUI: true, ui: { custom: review } } as unknown as ExtensionContext;
}

function contextWithoutUI(): ExtensionContext {
	return { hasUI: false } as unknown as ExtensionContext;
}

describe("plan tool Herdr state", () => {
	it("marks Herdr blocked only while plan review is open", async () => {
		const { pi, tool } = register();
		const lifecycle: string[] = [];
		pi.events.emit = (channel, data) => {
			const active = (data as { active: boolean }).active;
			lifecycle.push(`${channel}:${active}`);
			pi.emitted.push({ channel, data });
		};
		const ctx = contextWithReview(async () => {
			lifecycle.push("review");
			return "decline";
		});

		const result = await tool.execute("call-1", params, undefined, undefined, ctx);

		assert.deepEqual(lifecycle, ["herdr:blocked:true", "review", "herdr:blocked:false"]);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
		assert.equal(JSON.parse(result.content[0]?.text ?? "{}").status, "declined");
	});

	it("clears blocked state when plan review rejects", async () => {
		const { pi, tool } = register();
		const ctx = contextWithReview(async () => {
			throw new Error("review failed");
		});

		await assert.rejects(() => tool.execute("call-1", params, undefined, undefined, ctx), /review failed/);
		assert.deepEqual(pi.emitted, [blockedStart, blockedEnd]);
	});

	it("does not report blocked state when plan review has no UI", async () => {
		const { pi, tool } = register();

		const result = await tool.execute("call-1", params, undefined, undefined, contextWithoutUI());

		assert.deepEqual(pi.emitted, []);
		assert.equal(JSON.parse(result.content[0]?.text ?? "{}").status, "feedback");
	});
});
