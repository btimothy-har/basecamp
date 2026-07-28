import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	type CompactRequest,
	createHandoffLatch,
	dispatchImplementationHandoff,
} from "#tasks/workflows/handoff/dispatch.ts";
import {
	HANDOFF_COMPACTION_THRESHOLD_PERCENT,
	type PendingImplementationHandoff,
} from "#tasks/workflows/handoff/index.ts";

const handoff: PendingImplementationHandoff = {
	worktree: {
		label: "wt/continuation-guard",
		path: "/tmp/worktrees/wt/continuation-guard",
		branch: "bt/515c-continuation-guard",
		created: true,
		repoName: "basecamp",
		repoRoot: "/repo",
	},
	plan: {
		goal: "Ship the continuation guard",
		context: "Agents stop mid-work.",
		design: "Judge the stop against a rubric.",
		success: "Premature stops are nudged.",
		boundaries: "No daemon changes.",
		notes: {},
		tasks: [{ index: 0, label: "Implement", description: "Add the hook", criteria: "Tests pass", status: "pending" }],
	},
};

const OVER_THRESHOLD = HANDOFF_COMPACTION_THRESHOLD_PERCENT + 1;
const UNDER_THRESHOLD = HANDOFF_COMPACTION_THRESHOLD_PERCENT - 1;

function harness(contextUsagePercent: number | undefined) {
	const requests: CompactRequest[] = [];
	let sends = 0;
	const latch = createHandoffLatch();
	latch.arm();
	return {
		latch,
		requests,
		sends: () => sends,
		run(compact: (request: CompactRequest) => void = (request) => void requests.push(request)) {
			dispatchImplementationHandoff({
				handoff,
				contextUsagePercent,
				compact,
				send: () => {
					sends += 1;
					latch.disarm();
				},
			});
		},
	};
}

describe("handoff latch", () => {
	it("starts disarmed and reports each transition", () => {
		const latch = createHandoffLatch();
		assert.equal(latch.active, false);
		latch.arm();
		assert.equal(latch.active, true);
		latch.disarm();
		assert.equal(latch.active, false);
		latch.arm();
		assert.equal(latch.active, true);
	});
});

describe("dispatchImplementationHandoff", () => {
	it("sends immediately and skips compaction when the context has room", () => {
		const h = harness(UNDER_THRESHOLD);
		h.run();
		assert.equal(h.sends(), 1);
		assert.equal(h.requests.length, 0);
		assert.equal(h.latch.active, false);
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

	// The whole point of the latch: a peer agent_end handler inspecting state mid-compaction
	// must still see a restart in flight, or it will fire a competing one.
	it("keeps the latch armed across the entire compaction window", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();

		assert.equal(h.requests.length, 1);
		assert.equal(h.sends(), 0, "handoff must not be sent before compaction completes");
		assert.equal(h.latch.active, true, "latch must stay armed while compaction runs");
		assert.match(h.requests[0]?.customInstructions ?? "", /continuation guard/i);

		h.requests[0]?.onComplete();
		assert.equal(h.sends(), 1);
		assert.equal(h.latch.active, false);
	});

	it("still hands off when compaction fails", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();
		h.requests[0]?.onError();
		assert.equal(h.sends(), 1);
		assert.equal(h.latch.active, false);
	});

	it("still hands off when compaction throws synchronously", () => {
		const h = harness(OVER_THRESHOLD);
		h.run(() => {
			throw new Error("compaction unavailable");
		});
		assert.equal(h.sends(), 1);
		assert.equal(h.latch.active, false);
	});

	it("sends at most once when compaction reports both completion and failure", () => {
		const h = harness(OVER_THRESHOLD);
		h.run();
		h.requests[0]?.onComplete();
		h.requests[0]?.onError();
		h.requests[0]?.onComplete();
		assert.equal(h.sends(), 1);
	});
});
