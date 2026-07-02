import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { defaultTasksDir, registerTasks, type Task, tasksFilePath } from "../tasks/tasks.ts";

interface RegisteredToolResult {
	content: { type: "text"; text: string }[];
	details?: unknown;
	terminate?: boolean;
}

interface RegisteredTool {
	name: string;
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
		notes: null,
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
	const access = registerTasks(pi as unknown as ExtensionAPI);
	access.activateGoalCycle("Goal", [makeTask("first", "active"), makeTask("second")], null, null);
	return { pi, access, completeTask: pi.getTool("complete_task") };
}

describe("tasks path helpers", () => {
	it("builds task paths under the Basecamp tasks directory", () => {
		const homeDir = path.join("tmp", "home");
		const tasksDir = path.join(homeDir, ".pi", "basecamp", "tasks");

		assert.equal(defaultTasksDir(homeDir), tasksDir);
		assert.equal(tasksFilePath("session-1", defaultTasksDir(homeDir)), path.join(tasksDir, "session-1.json"));
	});
});

describe("complete_task stop_work", () => {
	it("continues normally when stop_work is omitted", async () => {
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
		assert.equal((result.details as { stop_work?: boolean }).stop_work, false);
		assert.equal(result.terminate, false);
		assert.deepEqual(patches, [undefined]);
		assert.deepEqual(notifications, []);
	});

	it("continues normally when stop_work is false", async () => {
		const { pi, completeTask } = setupTasks();
		const notifications: string[] = [];
		const result = await completeTask.execute("call-1", { task: 0, stop_work: false });

		const patches = await pi.emit(
			"tool_result",
			{
				type: "tool_result",
				toolCallId: "call-1",
				toolName: "complete_task",
				input: { task: 0, stop_work: false },
				content: result.content,
				details: result.details,
				isError: false,
			},
			makeContext(notifications),
		);

		assert.match(result.content[0]!.text, /Task 0 completed: first\./);
		assert.equal((result.details as { stop_work?: boolean }).stop_work, false);
		assert.equal(result.terminate, false);
		assert.deepEqual(patches, [undefined]);
		assert.deepEqual(notifications, []);
	});

	it("returns a termination signal and notifies when stop_work is true", async () => {
		const { pi, completeTask } = setupTasks();
		const notifications: string[] = [];
		const result = await completeTask.execute("call-1", { task: 0, stop_work: true });

		const patches = await pi.emit(
			"tool_result",
			{
				type: "tool_result",
				toolCallId: "call-1",
				toolName: "complete_task",
				input: { task: 0, stop_work: true },
				content: result.content,
				details: result.details,
				isError: false,
			},
			makeContext(notifications),
		);

		assert.match(result.content[0]!.text, /stop_work requested/);
		assert.equal((result.details as { stop_work?: boolean }).stop_work, true);
		assert.equal(result.terminate, true);
		assert.deepEqual(patches, [undefined]);
		assert.deepEqual(notifications, ["Task 0 completed: first. Stopping work now."]);
	});
});
