import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import { PROTOCOL_VERSION } from "#core/hub/protocol/index.ts";
import { registerAskAgentTool, registerPeerMessageTools } from "../daemon/tools.ts";
import {
	createMockPi,
	daemonToolDeps,
	installDaemonToolTestHooks,
	MockConnection,
	toolByName,
	trackSkillInvocation,
} from "./harness.ts";

describe("message_agent", () => {
	installDaemonToolTestHooks();

	it("registerPeerMessageTools registers message_agent and message_status", () => {
		const { pi, tools } = createMockPi();

		registerPeerMessageTools(pi, async () => new MockConnection(), daemonToolDeps);

		assert.deepEqual(
			tools.map((tool) => tool.name),
			["message_agent", "message_status"],
		);
	});

	it("message_agent and ask_agent describe known-public-handle contact across sessions", () => {
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => new MockConnection(), daemonToolDeps);
		registerAskAgentTool(pi, async () => new MockConnection(), daemonToolDeps);

		const messageDescription = toolByName(tools, "message_agent").description ?? "";
		const askDescription = toolByName(tools, "ask_agent").description ?? "";

		assert.match(messageDescription, /known public handle/i);
		assert.match(messageDescription, /without a live parent\/child\/sibling relationship/i);
		assert.match(askDescription, /known public handle/i);
		assert.match(askDescription, /without a live parent\/child\/sibling relationship/i);
	});

	it("message_agent sends peer_message and returns accepted message_id without waiting for delivery or answers", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");

		const executePromise = messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "Please consider this update.", interrupt: true },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));

		const outbound = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		assert.equal(outbound.type, "peer_message");
		assert.equal(outbound.target_handle, "amber-fox-a1b2c3");
		assert.equal(outbound.message, "Please consider this update.");
		assert.equal(outbound.interrupt, true);
		assert.equal(typeof outbound.request_id, "string");

		let resolved = false;
		executePromise.then(() => {
			resolved = true;
		});
		connection.emit({
			type: "peer_message_delivery",
			v: PROTOCOL_VERSION,
			message_id: "message-1",
			from_handle: "sender",
			from_relation: "peer",
			message: "recipient delivery is not a response",
			interrupt: false,
		});
		await new Promise((resolve) => setImmediate(resolve));
		assert.equal(resolved, false);

		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: "message-accepted",
			status: "accepted",
			error: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, undefined);
		assert.equal(result.details.agentHandle, "amber-fox-a1b2c3");
		assert.equal(result.details.messageId, "message-accepted");
		assert.equal(result.details.status, "accepted");
		assert.equal("agent_id" in result.details, false);
		assert.equal("run_id" in result.details, false);
		assert.match(result.content[0].text, /message_id message-accepted/);
		assert.doesNotMatch(result.content[0].text, /agent_id|run_id/);
	});

	it("message_agent handles unknown targets without leaking private ids", async () => {
		trackSkillInvocation("agents");
		const connection = new MockConnection();
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(pi, async () => connection, daemonToolDeps);
		const messageTool = toolByName(tools, "message_agent");

		const executePromise = messageTool.execute(
			"1",
			{ agent_handle: "missing-agent", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		await new Promise((resolve) => setImmediate(resolve));
		const outbound = connection.sent[0] as Extract<Frame, { type: "peer_message" }>;
		connection.emit({
			type: "peer_message_ack",
			v: PROTOCOL_VERSION,
			request_id: outbound.request_id,
			message_id: null,
			status: "unknown",
			error: null,
		});

		const result = await executePromise;
		assert.equal(result.isError, true);
		assert.equal(result.details.messageId, null);
		assert.equal(result.details.status, "unknown");
		assert.equal(result.content[0].text, "No available agent for that handle.");
		assert.doesNotMatch(result.content[0].text, /missing-agent/);
		assert.doesNotMatch(JSON.stringify(result), /agent_id|run_id/);
	});

	it("message_agent validates empty input and requires the agents skill", async () => {
		let connected = false;
		const { pi, tools } = createMockPi();
		registerPeerMessageTools(
			pi,
			async () => {
				connected = true;
				return new MockConnection();
			},
			daemonToolDeps,
		);
		const messageTool = toolByName(tools, "message_agent");

		const noSkill = await messageTool.execute(
			"1",
			{ agent_handle: "amber-fox-a1b2c3", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(noSkill.isError, true);
		assert.match(noSkill.content[0].text, /Load the agents skill first/);
		assert.equal(connected, false);

		trackSkillInvocation("agents");
		const emptyHandle = await messageTool.execute(
			"2",
			{ agent_handle: "   ", message: "hello" },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(emptyHandle.isError, true);
		assert.match(emptyHandle.content[0].text, /non-empty agent_handle/);
		assert.equal(connected, false);

		const emptyMessage = await messageTool.execute(
			"3",
			{ agent_handle: "amber-fox-a1b2c3", message: "   " },
			new AbortController().signal,
			() => {},
			{},
		);
		assert.equal(emptyMessage.isError, true);
		assert.match(emptyMessage.content[0].text, /non-empty message/);
		assert.equal(connected, false);
	});
});
