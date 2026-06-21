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

			const toolStart = pi.emit("tool_execution_start", { toolCallId: "tc-1", toolName: "read" });
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

			const telemetry = sent.filter(
				(frame): frame is Extract<Frame, { type: "telemetry" }> => frame.type === "telemetry",
			);
			assert.equal(telemetry.length, 3);
			assert.deepEqual(
				telemetry.map((frame) => frame.kind),
				["tool_execution_start", "tool_execution_end", "turn_end"],
			);

			const resultReport = sent.find(
				(frame): frame is Extract<Frame, { type: "result_report" }> => frame.type === "result_report",
			);
			assert.ok(resultReport);
			assert.equal(resultReport.run_id, "run-1");
			assert.equal(resultReport.agent_id, "agent-1");
			assert.equal(resultReport.status, "ok");
			assert.equal(resultReport.result, "final");
			assert.equal(resultReport.report_token, "token-for-tests");
			for (const frame of sent.filter(
				(candidate): candidate is Extract<Frame, { type: "telemetry" }> => candidate.type === "telemetry",
			)) {
				assert.equal(frame.report_token, "token-for-tests");
			}
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
