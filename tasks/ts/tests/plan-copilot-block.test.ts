import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { resetAgentMode, setAgentMode } from "#core/session/agent-mode.ts";
import { registerPlanCopilotGuard } from "../planning/plan-copilot-guard.ts";

type ToolCallEvent = { type: string; toolName: string; toolCallId: string; input: Record<string, unknown> };
type Handler = (event: ToolCallEvent) => unknown;

class FakePi {
	readonly handlers = new Map<string, Handler[]>();

	on(event: string, handler: Handler): void {
		const handlers = this.handlers.get(event) ?? [];
		handlers.push(handler);
		this.handlers.set(event, handlers);
	}
}

function registerHarness(): Handler {
	const pi = new FakePi();
	registerPlanCopilotGuard(pi as unknown as ExtensionAPI);
	const handler = pi.handlers.get("tool_call")?.[0];
	assert.ok(handler, "tool_call handler should be registered");
	return handler;
}

afterEach(() => {
	resetAgentMode();
});

describe("plan copilot guard", () => {
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
