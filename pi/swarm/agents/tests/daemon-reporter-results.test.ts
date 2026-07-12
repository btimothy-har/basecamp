import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { Frame } from "#core/hub/protocol/index.ts";
import type { DaemonConnection } from "../daemon/client.ts";
import { registerDaemonReporter } from "../daemon/reporter.ts";
import {
	BASECAMP_RUN_ATTEMPT,
	BASECAMP_RUN_RESULT_PATH,
	BASECAMP_RUNNER_MANAGED_RESULT,
	readRunResultSidecar,
} from "../daemon/run-result.ts";
import { MockPi } from "./harness.ts";
import {
	deferred,
	installReporterEnvHooks,
	telemetryFrames,
	tempRunResultPath,
	waitForFrameCount,
} from "./reporter-harness.ts";

describe("daemon reporter results", () => {
	installReporterEnvHooks();

	it("sends telemetry and final result report", async () => {
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

		const gate = deferred<DaemonConnection>();
		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			process.env.BASECAMP_REPORT_TOKEN = "token-for-tests";
			const pi = new MockPi();
			registerDaemonReporter(pi as unknown as any, {
				awaitConnection: () => gate.promise,
				runId: "run-1",
				agentId: "agent-1",
			});

			const toolStart = pi.emit("tool_execution_start", {
				toolCallId: "tc-1",
				toolName: "read",
				args: { path: "pi-swarm/extension/src/agents/daemon/reporter.ts" },
			});
			const toolEnd = pi.emit("tool_execution_end", { toolCallId: "tc-1", toolName: "read", isError: false });
			const turnEnd = pi.emit("turn_end", { turnIndex: 2, message: "ignore", toolResults: [] });
			const agentEnd = pi.emit("agent_end", {
				type: "agent_end",
				messages: [
					{ role: "assistant", content: [{ type: "text", text: "first" }] },
					{ role: "user", content: [{ type: "text", text: "nope" }] },
					{ role: "assistant", content: [{ type: "text", text: "final" }] },
				],
			});

			gate.resolve(connection);
			await Promise.all([toolStart, toolEnd, turnEnd, agentEnd]);
			await waitForFrameCount(sent, 7);

			const telemetry = telemetryFrames(sent);
			assert.deepEqual(
				telemetry.map((frame) => frame.kind),
				["tool_execution_start", "tool_call", "tool_execution_end", "tool_result", "turn_end", "agent_result"],
			);
			assert.deepEqual(telemetry.find((frame) => frame.kind === "tool_call")?.payload, {
				category: "tool",
				label: "read",
				snippet: "read pi-swarm/extension/src/agents/daemon/reporter.ts",
				toolName: "read",
			});
			assert.equal(telemetry.find((frame) => frame.kind === "tool_result")?.payload.snippet, "completed");
			assert.equal(telemetry.find((frame) => frame.kind === "agent_result")?.payload.snippet, "final");

			const resultReport = sent.find(
				(frame): frame is Extract<Frame, { type: "result_report" }> => frame.type === "result_report",
			);
			assert.ok(resultReport);
			assert.equal(resultReport.run_id, "run-1");
			assert.equal(resultReport.agent_id, "agent-1");
			assert.equal(resultReport.status, "ok");
			assert.equal(resultReport.result, "final");
			assert.equal(resultReport.report_token, "token-for-tests");
			for (const frame of telemetryFrames(sent)) {
				assert.equal(frame.report_token, "token-for-tests");
			}
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("writes runner-managed non-empty final result sidecar without result report", async () => {
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

		const runResultPath = await tempRunResultPath();
		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			process.env.BASECAMP_REPORT_TOKEN = "token-for-tests";
			process.env[BASECAMP_RUNNER_MANAGED_RESULT] = "1";
			process.env[BASECAMP_RUN_RESULT_PATH] = runResultPath;
			process.env[BASECAMP_RUN_ATTEMPT] = "2";
			const pi = new MockPi();
			registerDaemonReporter(pi as unknown as any, {
				awaitConnection: () => Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			await pi.emit("agent_end", {
				type: "agent_end",
				messages: [{ role: "assistant", content: [{ type: "text", text: "final" }] }],
			});
			await waitForFrameCount(sent, 1);

			const telemetry = telemetryFrames(sent);
			assert.deepEqual(
				telemetry.map((frame) => frame.kind),
				["agent_result"],
			);
			assert.equal(telemetry[0]?.payload.snippet, "final");
			assert.equal(
				sent.some((frame) => frame.type === "result_report"),
				false,
			);
			assert.deepEqual(await readRunResultSidecar(runResultPath), {
				run_id: "run-1",
				agent_id: "agent-1",
				attempts: [{ attempt: 2, status: "ok", result: "final", error: null }],
				final: null,
			});
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("writes runner-managed empty final result sidecar without result report", async () => {
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

		const runResultPath = await tempRunResultPath();
		const priorReportToken = process.env.BASECAMP_REPORT_TOKEN;
		try {
			process.env.BASECAMP_REPORT_TOKEN = "token-for-tests";
			process.env[BASECAMP_RUNNER_MANAGED_RESULT] = "1";
			process.env[BASECAMP_RUN_RESULT_PATH] = runResultPath;
			process.env[BASECAMP_RUN_ATTEMPT] = "1";
			const pi = new MockPi();
			registerDaemonReporter(pi as unknown as any, {
				awaitConnection: () => Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			await pi.emit("agent_end", {
				type: "agent_end",
				messages: [],
			});

			assert.deepEqual(sent, []);
			assert.deepEqual(await readRunResultSidecar(runResultPath), {
				run_id: "run-1",
				agent_id: "agent-1",
				attempts: [{ attempt: 1, status: "ok", result: "", error: null }],
				final: null,
			});
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("bounds agent result telemetry snippets", async () => {
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
				awaitConnection: () => Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			const finalText = "x".repeat(300);
			await pi.emit("agent_end", {
				type: "agent_end",
				messages: [{ role: "assistant", content: [{ type: "text", text: finalText }] }],
			});
			await waitForFrameCount(sent, 2);

			const telemetry = telemetryFrames(sent);
			const snippet = telemetry.find((frame) => frame.kind === "agent_result")?.payload.snippet;
			assert.equal(typeof snippet, "string");
			assert.equal((snippet as string).length, 240);
			assert.equal((snippet as string).endsWith("…"), true);
			assert.equal((snippet as string).includes(finalText), false);

			const resultReport = sent.find(
				(frame): frame is Extract<Frame, { type: "result_report" }> => frame.type === "result_report",
			);
			assert.equal(resultReport?.result, finalText);
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});

	it("emits full assistant message text with bounded snippets", async () => {
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
				awaitConnection: () => Promise.resolve(connection),
				runId: "run-1",
				agentId: "agent-1",
			});

			const text = `First line\n${"x".repeat(300)}`;
			await pi.emit("message_start", { message: { role: "assistant" } });
			await pi.emit("message_end", {
				message: {
					role: "assistant",
					content: [{ type: "text", text }],
				},
			});
			await waitForFrameCount(sent, 1);

			const output = telemetryFrames(sent).find((frame) => frame.kind === "assistant_output");
			assert.equal(output?.payload.text, text);
			assert.equal(typeof output?.payload.snippet, "string");
			assert.equal((output?.payload.snippet as string).length, 240);
			assert.equal((output?.payload.snippet as string).endsWith("…"), true);
		} finally {
			if (priorReportToken === undefined) delete process.env.BASECAMP_REPORT_TOKEN;
			else process.env.BASECAMP_REPORT_TOKEN = priorReportToken;
		}
	});
});
