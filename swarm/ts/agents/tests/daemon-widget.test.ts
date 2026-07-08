import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { RunSummaryAgent, RunSummaryResult } from "../daemon/client.ts";
import {
	ACTIVE_AGENTS_WIDGET_ID,
	activeRunningAgents,
	formatElapsed,
	publishActiveAgentsWidget,
	renderActiveAgentsWidgetLines,
	sanitizeWidgetText,
	startActiveAgentsWidget,
} from "../daemon/widget.ts";

interface WidgetSetCall {
	key: string;
	value: unknown;
	options: { placement?: string };
}

function widgetContext(calls: WidgetSetCall[], statusCalls: unknown[] = []): any {
	return {
		hasUI: true,
		ui: {
			theme: {
				fg: (_color: string, text: string) => text,
			},
			setWidget: (key: string, value: unknown, options: { placement?: string }) => {
				calls.push({ key, value, options });
			},
			setStatus: (...args: unknown[]) => {
				statusCalls.push(args);
			},
		},
	};
}

function runningAgent(overrides: Partial<RunSummaryAgent> = {}): RunSummaryAgent {
	return {
		agent_handle: "worker-1",
		agent_type: "worker",
		session_name: "Worker Session",
		status: "running",
		created_at: "2026-06-21T00:00:00.000Z",
		started_at: "2026-06-21T00:01:00.000Z",
		task: { goal: "Implement feature", current_task: { label: "Write tests", status: "active" } },
		...overrides,
	};
}

describe("active agents widget rendering", () => {
	it("auto-hides with no running agents and filters to running only", () => {
		const agents: RunSummaryAgent[] = [
			runningAgent({ status: "pending", agent_handle: "pending" }),
			runningAgent({ status: "completed", agent_handle: "done" }),
			runningAgent({ status: "failed", agent_handle: "failed" }),
		];

		assert.deepEqual(activeRunningAgents(agents), []);
		assert.deepEqual(renderActiveAgentsWidgetLines(agents), []);
	});

	it("caps rows and formats handle, type, task label, status, and elapsed duration", () => {
		const agents = [
			runningAgent({ agent_handle: "alpha", agent_type: "planner" }),
			runningAgent({ agent_handle: "beta", task: { goal: "Fallback goal", current_task: null } }),
			runningAgent({ agent_handle: "gamma" }),
		];

		const lines = renderActiveAgentsWidgetLines(agents, {
			limit: 2,
			nowMs: Date.parse("2026-06-21T00:04:30.000Z"),
		});

		assert.deepEqual(lines, [
			"● alpha [planner] — Write tests — running 3m",
			"● beta [worker] — Fallback goal — running 3m",
			"",
		]);
	});

	it("sanitizes and truncates display fields client-side", () => {
		assert.equal(sanitizeWidgetText(" \u001b[31mred\u001b[0m\n\ttext "), "red text");
		assert.equal(sanitizeWidgetText("\u001b]0;title\u0007Current task"), "Current task");
		assert.equal(sanitizeWidgetText("abcdef", 4), "abc…");

		const lines = renderActiveAgentsWidgetLines(
			[
				runningAgent({
					agent_handle: "\u001b[31mvery-long-agent-handle-with-newline\nunsafe\u001b[0m",
					agent_type: "type\twith\ncontrols",
					task: { goal: "x".repeat(60), current_task: null },
				}),
			],
			{ width: 70, nowMs: Date.parse("2026-06-21T00:01:30.000Z") },
		);

		assert.equal(lines.length, 2);
		assert.match(lines[0] ?? "", /^● very-long-agent-handle-with-new… \[type with controls\] — x+/);
		assert.equal((lines[0] ?? "").length, 70);
		assert.ok((lines[0] ?? "").endsWith("…"));
		assert.equal(lines[1], "");
	});

	it("formats elapsed duration from started_at or created_at", () => {
		const nowMs = Date.parse("2026-06-21T03:31:05.000Z");
		assert.equal(formatElapsed("2026-06-21T03:30:55.000Z", null, nowMs), "10s");
		assert.equal(formatElapsed(null, "2026-06-21T03:01:00.000Z", nowMs), "30m");
		assert.equal(formatElapsed("2026-06-21T01:00:00.000Z", null, nowMs), "2h 31m");
		assert.equal(formatElapsed("not-a-date", null, nowMs), "0s");
	});
});

describe("active agents widget lifecycle", () => {
	it("publishes multi-line below-editor widget with setWidget and does not use status", () => {
		const widgetCalls: WidgetSetCall[] = [];
		const statusCalls: unknown[] = [];
		const ctx = widgetContext(widgetCalls, statusCalls);

		publishActiveAgentsWidget(ctx, [runningAgent()], { nowMs: Date.parse("2026-06-21T00:02:00.000Z") });

		assert.equal(statusCalls.length, 0);
		assert.equal(widgetCalls.length, 1);
		assert.equal(widgetCalls[0]?.key, ACTIVE_AGENTS_WIDGET_ID);
		assert.deepEqual(widgetCalls[0]?.options, { placement: "belowEditor" });
		assert.equal(typeof widgetCalls[0]?.value, "function");

		const factory = widgetCalls[0]?.value as (
			tui: unknown,
			theme: { fg: (color: string, text: string) => string },
		) => {
			render: (width: number) => string[];
		};
		const rendered = factory(null, { fg: (_color, text) => text }).render(120);
		assert.equal(rendered.length, 2);
		assert.match(rendered[0] ?? "", /^● worker-1 \[worker\] — Write tests — running 1m$/);
		assert.equal(rendered[1], "");
	});

	it("clears widget when no running agents", () => {
		const widgetCalls: WidgetSetCall[] = [];
		const ctx = widgetContext(widgetCalls);

		publishActiveAgentsWidget(ctx, [runningAgent({ status: "completed" })]);

		assert.deepEqual(widgetCalls, [
			{ key: ACTIVE_AGENTS_WIDGET_ID, value: undefined, options: { placement: "belowEditor" } },
		]);
	});

	it("refreshes from summary and clears on fetch failure and stop", async () => {
		const widgetCalls: WidgetSetCall[] = [];
		const ctx = widgetContext(widgetCalls);
		const timers: Array<() => void> = [];
		let summary: RunSummaryResult | null = {
			agents: [
				runningAgent({ agent_handle: "live-1" }),
				runningAgent({ agent_handle: "live-2" }),
				runningAgent({ agent_handle: "live-3" }),
				runningAgent({ agent_handle: "live-4" }),
				runningAgent({ agent_handle: "live-5" }),
				runningAgent({ agent_handle: "live-6" }),
			],
		};

		const controller = startActiveAgentsWidget(ctx, {
			rootId: "root-1",
			socketPath: "/tmp/daemon.sock",
			refreshMs: 10,
			nowFn: () => Date.parse("2026-06-21T00:02:00.000Z"),
			fetchSummary: async (socketPath, rootId, limit) => {
				assert.equal(socketPath, "/tmp/daemon.sock");
				assert.equal(rootId, "root-1");
				assert.equal(limit, 50);
				return summary;
			},
			setIntervalFn: (handler) => {
				timers.push(handler);
				return 0 as unknown as ReturnType<typeof setInterval>;
			},
			clearIntervalFn: () => {},
		});

		await controller.refresh();
		assert.equal(widgetCalls.at(-1)?.key, ACTIVE_AGENTS_WIDGET_ID);
		assert.equal(typeof widgetCalls.at(-1)?.value, "function");
		const factory = widgetCalls.at(-1)?.value as (
			tui: unknown,
			theme: { fg: (color: string, text: string) => string },
		) => { render: (width: number) => string[] };
		const rendered = factory(null, { fg: (_color, text) => text }).render(120);
		assert.equal(rendered.length, 6);
		assert.match(rendered[0] ?? "", /^● live-1 \[worker\] — Write tests — running 1m$/);
		assert.equal(rendered[5], "");

		summary = null;
		await controller.refresh();
		assert.equal(widgetCalls.at(-1)?.value, undefined);

		summary = { agents: [runningAgent({ agent_handle: "timer" })] };
		assert.equal(timers.length, 1);
		timers[0]?.();
		await Promise.resolve();
		assert.equal(typeof widgetCalls.at(-1)?.value, "function");

		controller.stop();
		assert.equal(widgetCalls.at(-1)?.value, undefined);
	});
});
