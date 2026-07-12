import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import type { DaemonConnection } from "../daemon/client.ts";
import { type DaemonClientDeps, registerDaemonClient } from "../daemon/index.ts";
import { registerDaemonReporter } from "../daemon/reporter.ts";
import { MockPi } from "./harness.ts";
import { installReporterEnvHooks, telemetryFrames, waitForFrameCount } from "./reporter-harness.ts";

describe("daemon reporter", () => {
	installReporterEnvHooks();

	const deps: DaemonClientDeps = {
		hasInvokedSkill: () => true,
		getWorkspaceState: () => null,
		basecampExtensionRoot: process.cwd(),
		resolveModelAlias: (model: string) => model,
		formatTitle: () => "basecamp",
		shortSessionId: (value: string) => value.slice(-8),
	};

	it("emits skillName in skill tool call telemetry", async () => {
		const sent: Frame[] = [];
		const connection: DaemonConnection = {
			send(frame) {
				sent.push(frame);
			},
			on() {
				return () => {};
			},
			onClose() {
				return () => {};
			},
			close() {
				// no-op
			},
		};

		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			process.env.BASECAMP_REPORT_TOKEN = "token-for-tests";
			const pi = new MockPi();
			registerDaemonReporter(pi as unknown as any, {
				connectionPromise: Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			await pi.emit("tool_execution_start", {
				toolCallId: "tc-1",
				toolName: "skill",
				args: { name: "python-development" },
			});
			await waitForFrameCount(sent, 2);

			const toolCall = telemetryFrames(sent).find((frame) => frame.kind === "tool_call");
			assert.deepEqual(toolCall?.payload, {
				category: "tool",
				label: "skill",
				snippet: "skill python-development",
				toolName: "skill",
				skillName: "python-development",
			});
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("emits bounded assistant, thinking, and tool display activity", async () => {
		const sent: Frame[] = [];
		const connection: DaemonConnection = {
			send(frame) {
				sent.push(frame);
			},
			on() {
				return () => {};
			},
			onClose() {
				return () => {};
			},
			close() {
				// no-op
			},
		};
		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			process.env.BASECAMP_REPORT_TOKEN = "token-for-tests";
			const pi = new MockPi();
			registerDaemonReporter(pi as unknown as any, {
				connectionPromise: Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			await pi.emit("tool_execution_start", {
				toolCallId: "raw-tool-call-id",
				toolName: "bash",
				args: { command: "printf 'hello'", secret: "do-not-serialize" },
			});
			await pi.emit("tool_execution_end", {
				toolCallId: "raw-tool-call-id",
				toolName: "bash",
				isError: true,
				result: { content: [{ type: "text", text: "failure details\nwith multiple lines" }] },
			});
			await pi.emit("message_start", { message: { role: "assistant" } });
			await pi.emit("message_update", { delta: { type: "thinking_delta", text: "hidden chain of thought" } });
			await pi.emit("message_update", { delta: { type: "text_delta", text: "Visible " } });
			await pi.emit("message_end", {
				message: {
					role: "assistant",
					content: [
						{ type: "thinking", thinking: "hidden chain of thought" },
						{ type: "text", text: "Visible answer" },
					],
				},
			});
			await waitForFrameCount(sent, 6);

			const telemetry = telemetryFrames(sent);
			const toolCall = telemetry.find((frame) => frame.kind === "tool_call");
			assert.equal(toolCall?.payload.snippet, "bash printf 'hello'");
			assert.equal("toolCallId" in (toolCall?.payload ?? {}), false);
			assert.equal(JSON.stringify(toolCall?.payload).includes("do-not-serialize"), false);

			const toolResult = telemetry.find((frame) => frame.kind === "tool_result");
			assert.equal(toolResult?.payload.snippet, "error: failure details with multiple lines");
			assert.equal(toolResult?.payload.isError, true);

			const thinking = telemetry.find((frame) => frame.kind === "thinking");
			assert.deepEqual(thinking?.payload, {
				category: "assistant",
				label: "thinking",
				snippet: "thinking…",
			});
			assert.equal(JSON.stringify(telemetry).includes("hidden chain of thought"), false);

			const output = telemetry.find((frame) => frame.kind === "assistant_output");
			assert.equal(output?.payload.snippet, "Visible answer");
			assert.equal(output?.payload.text, "Visible answer");
			assert.equal(JSON.stringify(output?.payload).includes("hidden chain of thought"), false);
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("does not register hooks when report token is missing", () => {
		const pi = new MockPi();
		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			delete process.env.BASECAMP_REPORT_TOKEN;
			registerDaemonReporter(pi as unknown as any, {
				connectionPromise: Promise.resolve({} as DaemonConnection),
				runId: "run-1",
				agentId: "agent-1",
			});
			assert.equal(pi.handlers.size, 0);
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("registers ask_agent, peer message tools, and cancel_agent for daemon-spawned agents below max depth", () => {
		const pi = new MockPi();
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorMaxDepth = process.env.BASECAMP_AGENT_MAX_DEPTH;
		const priorRun = process.env.BASECAMP_RUN_ID;
		const priorAgent = process.env.BASECAMP_AGENT_ID;
		try {
			process.env.BASECAMP_AGENT_DEPTH = "1";
			process.env.BASECAMP_AGENT_MAX_DEPTH = "3";
			process.env.BASECAMP_RUN_ID = "run-1";
			process.env.BASECAMP_AGENT_ID = "agent-1";

			registerDaemonClient(pi as unknown as any, deps);

			assert.deepEqual(
				pi.tools.map((tool) => tool.name),
				["ask_agent", "message_agent", "message_status", "cancel_agent"],
			);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorMaxDepth === undefined) delete process.env.BASECAMP_AGENT_MAX_DEPTH;
			else process.env.BASECAMP_AGENT_MAX_DEPTH = priorMaxDepth;
			if (priorRun === undefined) delete process.env.BASECAMP_RUN_ID;
			else process.env.BASECAMP_RUN_ID = priorRun;
			if (priorAgent === undefined) delete process.env.BASECAMP_AGENT_ID;
			else process.env.BASECAMP_AGENT_ID = priorAgent;
		}
	});

	it("does nothing for depth>0 agents without BASECAMP_RUN_ID", () => {
		const pi = new MockPi();
		const priorDepth = process.env.BASECAMP_AGENT_DEPTH;
		const priorRun = process.env.BASECAMP_RUN_ID;
		try {
			process.env.BASECAMP_AGENT_DEPTH = "1";
			delete process.env.BASECAMP_RUN_ID;
			registerDaemonClient(pi as unknown as any, deps);
			assert.equal(pi.handlers.size, 0);
		} finally {
			if (priorDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
			else process.env.BASECAMP_AGENT_DEPTH = priorDepth;
			if (priorRun === undefined) delete process.env.BASECAMP_RUN_ID;
			else process.env.BASECAMP_RUN_ID = priorRun;
		}
	});
});
