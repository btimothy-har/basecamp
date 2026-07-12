import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "../../../hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "../../../hub/protocol/index.ts";
import { registerCancelAgentTool } from "../tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("cancel_agent", () => {
	installDaemonToolTestHooks();

	it("cancel_agent enforces agents skill, validates handles, and handles daemon disconnection", async () => {
		let connected = false;
		const { pi, tools } = createMockPi();
		registerCancelAgentTool(
			pi,
			async () => {
				connected = true;
				return null;
			},
			daemonToolDeps,
		);
		const cancelTool = toolByName(tools, "cancel_agent");

		const noSkill = await cancelTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(noSkill.isError, true);
		assert.match(noSkill.content[0].text, /Load the agents skill first/);
		assert.equal(noSkill.details, null);
		assert.equal(connected, false);

		trackSkillInvocation("agents");
		const emptyHandle = await cancelTool.execute(
			"2",
			{ agent_handle: "   " },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(emptyHandle.isError, true);
		assert.match(emptyHandle.content[0].text, /non-empty agent_handle/);
		assert.equal(emptyHandle.details, null);
		assert.equal(connected, false);

		const notConnected = await cancelTool.execute(
			"3",
			{ agent_handle: "amber-fox-a1b2c3" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(notConnected.isError, true);
		assert.equal(notConnected.content[0].text, "basecamp hub is not connected; cannot cancel agents.");
		assert.equal(notConnected.details, null);
		assert.equal(connected, true);
	});

	it("cancel_agent maps daemon ack statuses to text, error state, and public details", async () => {
		trackSkillInvocation("agents");
		const cases = [
			{
				status: "cancelled" as const,
				error: null,
				isError: undefined,
				text: "cancelled amber-fox-a1b2c3",
			},
			{
				status: "already_terminal" as const,
				error: "already done",
				isError: undefined,
				text: "amber-fox-a1b2c3 is not running (already finished or never started).",
			},
			{
				status: "not_found" as const,
				error: "missing",
				isError: true,
				text: "No agent found for handle amber-fox-a1b2c3.",
			},
			{
				status: "not_authorized" as const,
				error: "outside subtree",
				isError: true,
				text: "You can only cancel agents you dispatched.",
			},
		];

		for (const item of cases) {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			registerCancelAgentTool(pi, async () => connection, daemonToolDeps);
			const cancelTool = toolByName(tools, "cancel_agent");

			const executePromise = cancelTool.execute(
				"1",
				{ agent_handle: " amber-fox-a1b2c3 " },
				new AbortController().signal,
				() => {},
				{},
			);
			await new Promise((resolve) => setImmediate(resolve));

			const outbound = connection.sent[0] as Extract<Frame, { type: "cancel" }>;
			assert.equal(outbound.type, "cancel");
			assert.equal(outbound.target_handle, "amber-fox-a1b2c3");
			assert.equal(typeof outbound.request_id, "string");

			connection.emit({
				type: "cancel_ack",
				v: PROTOCOL_VERSION,
				request_id: outbound.request_id,
				status: item.status,
				error: item.error,
			});

			const result = await executePromise;
			assert.equal(result.isError, item.isError);
			assert.equal(result.content[0].text, item.text);
			assert.deepEqual(result.details, {
				agentHandle: "amber-fox-a1b2c3",
				status: item.status,
				error: item.error,
			});
			assert.equal("agent_id" in result.details, false);
			assert.equal("run_id" in result.details, false);
		}
	});
});
