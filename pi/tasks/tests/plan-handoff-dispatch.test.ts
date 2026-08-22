import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	COMPACTION_WATCHDOG_MS,
	type CompactRequest,
	dispatchImplementationHandoff,
} from "#tasks/workflows/handoff/dispatch.ts";
import {
	HANDOFF_COMPACTION_THRESHOLD_PERCENT,
	type PendingImplementationHandoff,
} from "#tasks/workflows/handoff/index.ts";

const handoff: PendingImplementationHandoff = {
	worktree: {
		label: "wt/tasks-plan",
		path: "/tmp/worktrees/wt/tasks-plan",
		branch: "bt/515c-tasks-plan",
		created: true,
		repoName: "basecamp",
		repoRoot: "/repo",
	},
	plan: {
		goal: "Ship the tasks-plan feature",
		context: "Work needs a plan.",
		design: "Approve a structured plan, then hand off.",
		success: "The plan is approved and handed off.",
		boundaries: "No daemon changes.",
		notes: {},
		tasks: [{ index: 0, label: "Implement", description: "Do the work", criteria: "Tests pass", status: "pending" }],
	},
};

const OVER_THRESHOLD = HANDOFF_COMPACTION_THRESHOLD_PERCENT + 1;
const UNDER_THRESHOLD = HANDOFF_COMPACTION_THRESHOLD_PERCENT - 1;

function harness(contextUsagePercent: number | undefined) {
	const requests: CompactRequest[] = [];
	let sends = 0;
	let watchdog: (() => void) | null = null;
	let cancelled = 0;
	return {
		requests,
		sends: () => sends,
		cancelled: () => cancelled,
		scheduledDelay: null as number | null,
		/** Fires the watchdog the dispatcher armed, standing in for the elapsed bound. */
		fireWatchdog(): void {
			assert.ok(watchdog, "no watchdog was scheduled");
			watchdog();
		},
		run(compact: (request: CompactRequest) => void = (request) => void requests.push(request)) {
			dispatchImplementationHandoff({
				handoff,
				contextUsagePercent,
				compact,
				schedule: (fn, ms) => {
					watchdog = fn;
					this.scheduledDelay = ms;
					return () => {
						cancelled += 1;
					};
				},
				send: () => {
					sends += 1;
				},
			});
		},
	};
}

describe("dispatchImplementationHandoff", () => {
	it("sends immediately and skips compaction when the context has room", () => {
		const h = harness(UNDER_THRESHOLD);
		h.run();
		assert.equal(h.sends(), 1);
		assert.equal(h.requests.length, 0);
	});

	it("sends immediately when context usage is unknown", () => {
		const h = harness(undefined);
		h.run();
		assert.equal(h.sends(), 1);
		assert.equal(h.requests.length, 0);
	});

	it("does not treat usage exactly at the threshold as full", () => {
		const h = harness(HANDOFF_COMPACTION_THRESHOLD_PERCENT);
		h.run();
		assert.equal(h.sends(), 1);
		assert.equal(h.requests.length, 0);
	});

	it("sends nothing until the compaction pass reports, embedding the approved plan in its instructions", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();

		assert.equal(h.requests.length, 1);
		assert.equal(h.sends(), 0, "handoff must not be sent before compaction completes");
		assert.match(h.requests[0]?.customInstructions ?? "", /Ship the tasks-plan feature/);

		h.requests[0]?.onComplete();
		assert.equal(h.sends(), 1);
	});

	it("still hands off when compaction fails", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();
		h.requests[0]?.onError();
		assert.equal(h.sends(), 1);
	});

	it("still hands off when compaction throws synchronously", () => {
		const h = harness(OVER_THRESHOLD);
		h.run(() => {
			throw new Error("compaction unavailable");
		});
		assert.equal(h.sends(), 1);
	});

	it("sends at most once when compaction reports both completion and failure", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();
		h.requests[0]?.onComplete();
		h.requests[0]?.onError();
		h.requests[0]?.onComplete();
		assert.equal(h.sends(), 1);
	});

	// A compaction that never reports would strand the handoff for the whole session.
	it("hands off when compaction never reports", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();

		assert.equal(h.scheduledDelay, COMPACTION_WATCHDOG_MS);
		assert.equal(h.sends(), 0);

		h.fireWatchdog();

		assert.equal(h.sends(), 1, "the handoff still goes out");
	});

	it("cancels the watchdog once compaction reports, and still sends only once", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();
		h.requests[0]?.onComplete();

		assert.equal(h.cancelled(), 1);
		h.fireWatchdog();
		assert.equal(h.sends(), 1, "a late watchdog cannot double-send");
	});

	it("does not schedule a watchdog when no compaction is needed", () => {
		const h = harness(UNDER_THRESHOLD);
		h.run();
		assert.equal(h.scheduledDelay, null);
		assert.equal(h.sends(), 1);
	});
});
