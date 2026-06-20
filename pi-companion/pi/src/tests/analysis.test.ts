import assert from "node:assert/strict";
import type { ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { describe, it } from "node:test";
import type { SessionEntry } from "@earendil-works/pi-coding-agent";
import {
	type AnalysisDeps,
	type AnalysisState,
	buildAlreadyTracked,
	buildEnvelope,
	countUserTurns,
	MIN_USER_TURNS,
	maybeRunAnalysis,
} from "../analysis.ts";

function entry(message: unknown): SessionEntry {
	return { type: "message", message } as unknown as SessionEntry;
}

class FakeChild extends EventEmitter {
	public stdinData: string | null = null;
	public killed = false;
	public stdin = {
		end: (value?: string) => {
			this.stdinData = value ?? null;
		},
	};

	kill(): boolean {
		this.killed = true;
		return true;
	}
}

describe("companion/analysis helpers", () => {
	it("countUserTurns counts only user messages", () => {
		const branch: SessionEntry[] = [
			entry({ role: "user", content: "first" }),
			entry({ role: "assistant", content: [{ type: "text", text: "reply" }] }),
			entry({ role: "toolResult", toolName: "read", isError: false, content: [{ type: "text", text: "ok" }] }),
			entry({ role: "user", content: "second" }),
		];

		assert.equal(countUserTurns(branch), 2);
	});

	it("buildAlreadyTracked formats goal and non-deleted tasks", () => {
		const tracked = buildAlreadyTracked({
			goal: "Ship dashboard",
			tasks: [
				{ label: "Implement producer", status: "active" },
				{ label: "Old task", status: "deleted" },
				{ label: "Add tests", status: "pending" },
			],
		});

		assert.equal(tracked, "Goal: Ship dashboard\nTasks:\n[active] Implement producer\n[pending] Add tests");
		assert.equal(
			buildAlreadyTracked({
				goal: null,
				tasks: [{ label: "Old task", status: "deleted" }],
			}),
			"",
		);
		assert.equal(buildAlreadyTracked(null), "");
	});
});

describe("maybeRunAnalysis", () => {
	function baseDeps(overrides: Partial<AnalysisDeps> = {}): AnalysisDeps {
		return {
			isActive: () => true,
			branch: [entry({ role: "user", content: "first" }), entry({ role: "user", content: "second" })],
			sessionId: "session-123",
			tasksState: { goal: "Goal", tasks: [{ label: "Task", status: "pending" }] },
			cwd: "/tmp/worktree",
			spawnFn: (() => {
				throw new Error("spawnFn not configured");
			}) as unknown as AnalysisDeps["spawnFn"],
			...overrides,
		};
	}

	it("skips when state is already inFlight", () => {
		const state: AnalysisState = { inFlight: true, child: null };
		let called = 0;

		maybeRunAnalysis(
			state,
			baseDeps({
				spawnFn: (() => {
					called += 1;
					return new FakeChild() as unknown as ChildProcess;
				}) as unknown as AnalysisDeps["spawnFn"],
			}),
		);

		assert.equal(called, 0);
	});

	it("skips when companion pane is inactive", () => {
		const state: AnalysisState = { inFlight: false, child: null };
		let called = 0;

		maybeRunAnalysis(
			state,
			baseDeps({
				isActive: () => false,
				spawnFn: (() => {
					called += 1;
					return new FakeChild() as unknown as ChildProcess;
				}) as unknown as AnalysisDeps["spawnFn"],
			}),
		);

		assert.equal(called, 0);
	});

	it("skips when below minimum user turns", () => {
		const state: AnalysisState = { inFlight: false, child: null };
		let called = 0;

		maybeRunAnalysis(
			state,
			baseDeps({
				branch: [entry({ role: "user", content: "only one" })],
				spawnFn: (() => {
					called += 1;
					return new FakeChild() as unknown as ChildProcess;
				}) as unknown as AnalysisDeps["spawnFn"],
			}),
		);

		assert.equal(MIN_USER_TURNS, 2);
		assert.equal(called, 0);
	});

	it("spawns, writes envelope, and returns synchronously without waiting for close", () => {
		const state: AnalysisState = { inFlight: false, child: null };
		const child = new FakeChild();
		const calls: Array<{ command: string; args: string[]; cwd: string }> = [];

		const spawnFn = ((command: string, args: string[], options: { cwd: string }) => {
			calls.push({ command, args, cwd: options.cwd });
			return child as unknown as ChildProcess;
		}) as unknown as AnalysisDeps["spawnFn"];

		maybeRunAnalysis(
			state,
			baseDeps({
				spawnFn,
				tasksState: {
					goal: "Ship dashboard",
					tasks: [
						{ label: "Implement producer", status: "active" },
						{ label: "Ignore me", status: "deleted" },
					],
				},
			}),
		);

		assert.equal(calls.length, 1);
		assert.equal(calls[0]?.command, "basecamp");
		assert.deepEqual(calls[0]?.args, ["companion-analyze", "--session-id", "session-123"]);
		assert.equal(calls[0]?.cwd, "/tmp/worktree");

		const expectedEnvelope = buildEnvelope(
			"[User]\nfirst\n\n[User]\nsecond",
			"Goal: Ship dashboard\nTasks:\n[active] Implement producer",
		);
		assert.equal(child.stdinData, expectedEnvelope);

		assert.equal(state.inFlight, true);
		assert.equal(state.child, child);
	});

	it("clears inFlight when child emits close", () => {
		const state: AnalysisState = { inFlight: false, child: null };
		const child = new FakeChild();

		const spawnFn = (() => child as unknown as ChildProcess) as unknown as AnalysisDeps["spawnFn"];

		maybeRunAnalysis(state, baseDeps({ spawnFn }));
		assert.equal(state.inFlight, true);

		child.emit("close", 0);
		assert.equal(state.inFlight, false);
		assert.equal(state.child, null);
	});
});
