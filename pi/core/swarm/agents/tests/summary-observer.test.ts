import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { RunSummaryResult } from "../client.ts";
import { observeRunSummary, publishRunSummary } from "../summary-observer.ts";

describe("run summary observer", () => {
	it("replays the latest summary and stops after unsubscribe", () => {
		const latest: RunSummaryResult = {
			counts: { pending: 0, running: 1, completed: 0, failed: 0, total: 1 },
			agents: [],
		};
		publishRunSummary(latest);
		const observed: Array<RunSummaryResult | null> = [];
		const unsubscribe = observeRunSummary((summary) => observed.push(summary));

		publishRunSummary(null);
		unsubscribe();
		publishRunSummary({ agents: [] });

		assert.deepEqual(observed, [latest, null]);
		publishRunSummary(null);
	});
});
