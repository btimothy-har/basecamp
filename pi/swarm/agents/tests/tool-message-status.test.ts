import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { registerPeerMessageTools } from "../tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("message_status", () => {
	installDaemonToolTestHooks();

	it("message_status sends status requests and returns lifecycle fields for all statuses", async () => {
		trackSkillInvocation("agents");
		const statuses = ["accepted", "sent", "queued", "failed", "unavailable", "unknown"] as const;
		for (const status of statuses) {
			const connection = new MockConnection();
			const { pi, tools } = createMockPi();
			registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
			const statusTool = toolByName(tools, "message_status");

			const executePromise = statusTool.execute(
				"1",
				{ message_id: `message-${status}` },
				new AbortController().signal,
				() => {},
				{},
			);
			await new Promise((resolve) => setImmediate(resolve));
			const outbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
			assert.equal(outbound.type, "message_status");
			assert.equal(typeof outbound.request_id, "string");
			assert.equal(outbound.message_id, `message-${status}`);
			assert.equal(outbound.wait_until_delivery, false);
			assert.equal(outbound.timeout_s, undefined);

			connection.emit({
				type: "message_status_result",
				v: PROTOCOL_VERSION,
				request_id: outbound.request_id,
				message_id: `message-${status}`,
				status,
				error: status === "failed" ? "delivery failed" : null,
				created_at: "2026-01-01T00:00:00Z",
				sent_at: status === "sent" || status === "queued" ? "2026-01-01T00:00:01Z" : null,
				queued_at: status === "queued" ? "2026-01-01T00:00:02Z" : null,
				failed_at: status === "failed" ? "2026-01-01T00:00:03Z" : null,
			});

			const result = await executePromise;
			assert.equal(result.isError, undefined);
			assert.equal(result.details.messageId, `message-${status}`);
			assert.equal(result.details.status, status);
			assert.equal(result.details.createdAt, "2026-01-01T00:00:00Z");
			const expectedStatusText = status === "queued" ? "queued in recipient session" : status;
			assert.match(result.content[0].text, new RegExp(`status ${expectedStatusText}`));
			assert.doesNotMatch(JSON.stringify(result), /answer|agent_id|run_id/);
		}
	});

	it("message_status supports wait flag, timeout, abort, validation, and skill enforcement", async () => {
		let connected = false;
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(
			pi,
			async () => {
				connected = true;
				return connection;
			},
			daemonToolDeps,
		);
		const statusTool = toolByName(tools, "message_status");

		const noSkill = await statusTool.execute(
			"1",
			{ message_id: "message-1" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(noSkill.isError, true);
		assert.match(noSkill.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);

		trackSkillInvocation("agents");
		const emptyId = await statusTool.execute("2", { message_id: "   " }, new AbortController().signal, () => {}, {});
		assert.equal(emptyId.isError, true);
		assert.match(emptyId.content[0].text, /non-empty message_id/);
		assert.equal(connected, false);

		const executePromise = statusTool.execute(
			"3",
			{ message_id: "message-wait", wait_until_delivery: true, timeout_s: 12.8 },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "message_status" }>;
		assert.equal(typeof outbound.request_id, "string");
		assert.equal(outbound.wait_until_delivery, true);
		assert.equal(outbound.timeout_s, 12);
		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-wait",
			status: "unavailable",
			error: "target offline",
			created_at: "2026-01-01T00:00:00Z",
			sent_at: null,
			queued_at: null,
			failed_at: "2026-01-01T00:00:04Z",
		});
		const waitResult = await executePromise;
		assert.equal(waitResult.details.status, "unavailable");
		assert.equal(waitResult.details.error, "target offline");

		const controller = new AbortController();
		const abortPromise = statusTool.execute(
			"4",
			{ message_id: "message-abort", wait_until_delivery: true, timeout_s: 30 },
			controller.signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		controller.abort();
		const abortResult = await abortPromise;
		assert.equal(abortResult.details.aborted, true);
		assert.match(abortResult.content[0].text, /aborted/);
	});

	it("peer message renderers stay compact and do not expose private ids", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");
		const statusTool = toolByName(tools, "message_status");
		const theme = { fg: (_token: string, text: string) => `styled:${text}` };

		const messagePromise = messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const peer = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: peer.request_id,
			message_id: "message-render",
			status: "accepted",
			error: null,
		});
		const messageResult = await messagePromise;
		const renderedMessage = (messageTool as any).renderResult(messageResult, {}, theme).render(120).join("\n");
		assert.match(renderedMessage, /message_id message-render/);
		assert.doesNotMatch(renderedMessage, /agent_id|run_id|00000000-0000-4000-8000/);

		const statusPromise = statusTool.execute(
			"2",
			{ message_id: "message-render" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const status = connection.sent[1] as Extract<Frame, { type: "message_status" }>;
		connection.emit({
			type: "message_status_result",
			v: PROTOCOL_VERSION,
			request_id: status.request_id,
			message_id: "message-render",
			status: "queued",
			error: null,
			created_at: "2026-01-01T00:00:00Z",
			sent_at: "2026-01-01T00:00:01Z",
			queued_at: "2026-01-01T00:00:02Z",
			failed_at: null,
		});
		const statusResult = await statusPromise;
		const renderedStatus = (statusTool as any).renderResult(statusResult, {}, theme).render(120).join("\n");
		assert.match(renderedStatus, /message_id message-render/);
		assert.match(renderedStatus, /status queued in recipient session/);
		assert.doesNotMatch(renderedStatus, /answer|agent_id|run_id/);
	});
});
