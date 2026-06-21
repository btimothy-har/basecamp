import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { PiSwarmDependencies } from "../../dependencies.ts";
import type { DaemonConnection } from "../daemon/client.ts";
import type { Frame } from "../daemon/frames.ts";
import { registerDaemonClient } from "../daemon/index.ts";
import { registerDaemonReporter } from "../daemon/reporter.ts";

class MockPi {
	handlers = new Map<string, Array<(event: unknown, ctx?: unknown) => unknown>>();

	on(type: string, handler: (event: unknown, ctx?: unknown) => unknown): void {
		const list = this.handlers.get(type) ?? [];
		list.push(handler);
		this.handlers.set(type, list);
	}

	async emit(type: string, event: unknown): Promise<void> {
		const handlers = this.handlers.get(type) ?? [];
		for (const handler of handlers) {
			await handler(event);
		}
	}
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

async function waitForFrameCount(sent: Frame[], count: number): Promise<void> {
	for (let attempt = 0; attempt < 20; attempt++) {
		if (sent.length >= count) return;
		await new Promise((resolve) => setTimeout(resolve, 0));
	}
	assert.equal(sent.length, count);
}

function telemetryFrames(sent: Frame[]): Array<Extract<Frame, { type: "telemetry" }>> {
	return sent.filter((frame): frame is Extract<Frame, { type: "telemetry" }> => frame.type === "telemetry");
}

describe("daemon reporter", () => {
	const deps = {
		hasInvokedSkill: () => true,
		getWorkspaceState: () => null,
		basecampExtensionRoot: process.cwd(),
		resolveModelAlias: (model: string) => model,
		readSkillContent: () => null,
		buildSkillBlock: () => "",
		formatTaskProgressSummary: () => null,
		renderCompactTaskProgressLines: () => [],
		formatTitle: () => "basecamp",
		shortSessionId: (value: string) => value.slice(-8),
		registerCatalogProvider: () => {
			/* no-op */
		},
	} as unknown as PiSwarmDependencies;

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
				connectionPromise: gate.promise,
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
				connectionPromise: Promise.resolve(connection),
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
