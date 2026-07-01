import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resetAgentMode, setAgentMode } from "pi-core/session/agent-mode.ts";
import { registerPlan } from "../planning/plan.ts";
import { type PlanDraft, SECTION_NAMES } from "../planning/review.ts";
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

async function executeText(tool: RegisteredTool, params: Record<string, unknown>): Promise<string> {
	const result = await tool.execute("1", params, new AbortController().signal, () => {}, createContext());
	const first = result.content[0];
	assert.equal(first?.type, "text");
	return first.text;
}

describe("plan execution result shapes", () => {
	afterEach(() => {
		resetAgentMode();
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

	it("returns workstream graph/status fields for approved workstream plans", async () => {
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

		assert.equal(approved.status, "approved");
		assert.equal(approved.plan_kind, "workstreams");
		assert.equal(approved.implementation_mode, "supervisor");
		assert.equal(approved.handoff_status, "pending_workstream_activation");
		assert.deepEqual(approved.workstream_progress, { ready: 1, blocked: 2, total: 3 });
		assert.deepEqual(approved.workstream_graph, { ready: ["core"], blocked: { ui: ["core"], e2e: ["ui"] } });
		assert.equal(approved.workstreams.core.status, "ready");
		assert.equal(approved.workstreams.core.worktreeSlug, "core-work");
		assert.equal(approved.workstreams.ui.status, "blocked");
		assert.equal(approved.workstreams.ui.worktreeSlug, undefined);
		assert.equal(approved.workstreams.e2e.status, "blocked");
		assert.equal(approved.tasks, undefined);
		assert.equal(tasksAccess.activated, null);
	});
});
