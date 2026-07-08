import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resetAgentMode, setAgentMode } from "pi-core/session/agent-mode.ts";
import { registerPlan } from "../planning/plan.ts";
import type { TasksAccess } from "../tasks/tasks.ts";

type Handler = (event: {
	type: string;
	toolName: string;
	toolCallId: string;
	input: Record<string, unknown>;
}) => unknown;

class FakePi {
	readonly handlers = new Map<string, Handler[]>();

	on(event: string, handler: Handler): void {
		const handlers = this.handlers.get(event) ?? [];
		handlers.push(handler);
		this.handlers.set(event, handlers);
	}

	registerTool(): void {}

	registerCommand(): void {}

	registerFlag(): void {}
}

function registerHarness(): Handler {
	const pi = new FakePi();
	registerPlan(pi as unknown as ExtensionAPI, {} as unknown as TasksAccess);
	const handler = pi.handlers.get("tool_call")?.[0];
	assert.ok(handler, "tool_call handler should be registered");
	return handler;
}

afterEach(() => {
	resetAgentMode();
});

describe("plan tool copilot block", () => {
	it("blocks plan tool calls in copilot mode", async () => {
		const handler = registerHarness();
		setAgentMode("copilot");

		const result = await handler({ type: "tool_call", toolName: "plan", toolCallId: "t1", input: {} });

		assert.equal((result as { block?: boolean }).block, true);
		assert.match((result as { reason?: string }).reason ?? "", /disabled in copilot/);
		assert.match((result as { reason?: string }).reason ?? "", /launch_workstream/);
	});

	it("does not block plan tool calls outside copilot mode", async () => {
		const handler = registerHarness();
		setAgentMode("executor");

		const result = await handler({ type: "tool_call", toolName: "plan", toolCallId: "t1", input: {} });

		assert.equal(result, undefined);
	});

	it("does not block non-plan tool calls in copilot mode", async () => {
		const handler = registerHarness();
		setAgentMode("copilot");

		const result = await handler({ type: "tool_call", toolName: "bash", toolCallId: "t1", input: {} });

		assert.equal(result, undefined);
	});
});
