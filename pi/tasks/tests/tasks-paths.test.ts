import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { startGoalCycle } from "#tasks/lifecycle/goal-cycle.ts";
import { defaultTasksDir, registerTasks, tasksFilePath } from "#tasks/lifecycle/index.ts";
import type { Task } from "#tasks/schemas/task.ts";
import { registerTaskGuards } from "#tasks/tools/guards.ts";
import { registerTaskTools } from "#tasks/tools/task-tools.ts";

interface RegisteredToolResult {
	content: { type: "text"; text: string }[];
	details?: unknown;
	terminate?: boolean;
}

interface RegisteredTool {
	name: string;
	parameters: { properties: Record<string, unknown> };
	execute(toolCallId: string, params: Record<string, unknown>): Promise<RegisteredToolResult>;
}

type RegisteredHandler = (event: Record<string, unknown>, ctx: ExtensionContext) => unknown | Promise<unknown>;

class FakePi {
	readonly tools = new Map<string, RegisteredTool>();
	readonly handlers = new Map<string, RegisteredHandler[]>();

	registerTool(tool: RegisteredTool): void {
		this.tools.set(tool.name, tool);
	}

	on(eventName: string, handler: RegisteredHandler): void {
		const handlers = this.handlers.get(eventName) ?? [];
		handlers.push(handler);
		this.handlers.set(eventName, handlers);
	}

	sendMessage(): void {}

	getTool(name: string): RegisteredTool {
		const tool = this.tools.get(name);
		assert.ok(tool, `${name} tool should be registered`);
		return tool;
	}

	async emit(eventName: string, event: Record<string, unknown>, ctx: ExtensionContext): Promise<unknown[]> {
		const handlers = this.handlers.get(eventName) ?? [];
		return Promise.all(handlers.map((handler) => handler(event, ctx)));
	}
}

function makeTask(label: string, status: Task["status"] = "pending"): Task {
	return {
		label,
		description: `Do ${label}`,
		criteria: `${label} done`,
		status,
		review: null,
	};
}

function makeContext(notifications: string[]): ExtensionContext {
	return {
		hasUI: true,
		ui: {
			notify(message: string) {
				notifications.push(message);
			},
		},
	} as unknown as ExtensionContext;
}

function setupTasks() {
	const pi = new FakePi();
	const runtime = registerTasks(pi as unknown as ExtensionAPI);
	registerTaskTools(pi as unknown as ExtensionAPI, runtime);
	registerTaskGuards(pi as unknown as ExtensionAPI, runtime);
	startGoalCycle(runtime, {
		goal: "Goal",
		tasks: [makeTask("first", "active"), makeTask("second")],
		planRef: null,
		agentMode: null,
	});
	return { pi, completeTask: pi.getTool("complete_task") };
}

describe("tasks path helpers", () => {
	it("builds task paths under the Basecamp tasks directory", () => {
		const homeDir = path.join("tmp", "home");
		const tasksDir = path.join(homeDir, ".pi", "basecamp", "tasks");

		assert.equal(defaultTasksDir(homeDir), tasksDir);
		assert.equal(tasksFilePath("session-1", defaultTasksDir(homeDir)), path.join(tasksDir, "session-1.json"));
	});
});

describe("complete_task", () => {
	it("completes a task without terminating the agent loop", async () => {
		const { pi, completeTask } = setupTasks();
		const notifications: string[] = [];
		const result = await completeTask.execute("call-1", { task: 0 });

		const patches = await pi.emit(
			"tool_result",
			{
				type: "tool_result",
				toolCallId: "call-1",
				toolName: "complete_task",
				input: { task: 0 },
				content: result.content,
				details: result.details,
				isError: false,
			},
			makeContext(notifications),
		);

		assert.match(result.content[0]!.text, /Task 0 completed: first\./);
		assert.match(result.content[0]!.text, /Progress: 1\/2 tasks completed\./);
		// Closing out is a work summary now, so no tool result may end the loop early.
		assert.equal(result.terminate, undefined);
		// No tasks-domain tool_result handler remains: the stop-work notifier went with the parameter.
		assert.deepEqual(patches, []);
		assert.deepEqual(notifications, []);
	});

	// The loop-termination affordance is gone: nothing an agent can pass ends the run early.
	it("exposes no stop_work parameter", () => {
		const { completeTask } = setupTasks();
		assert.deepEqual(Object.keys(completeTask.parameters.properties), ["task"]);
	});
});
