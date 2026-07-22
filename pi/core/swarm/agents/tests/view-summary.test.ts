import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildRunSummaryPath, parseRunSummaryResponse } from "../view/summary.ts";

describe("run summary view", () => {
	it("encodes root_id and clamps limits in the summary path", () => {
		assert.equal(
			buildRunSummaryPath("root id/with?chars", 500),
			"/runs/summary?root_id=root%20id%2Fwith%3Fchars&limit=50",
		);
		assert.equal(buildRunSummaryPath("root", -12), "/runs/summary?root_id=root&limit=0");
		assert.equal(buildRunSummaryPath("root", 4.8), "/runs/summary?root_id=root&limit=4");
	});

	it("parses widget fields and ignores malformed or retired detail", () => {
		const result = parseRunSummaryResponse({
			root_id: "root",
			counts: { pending: 1, running: 2, completed: 3, failed: 4, total: 10 },
			agents: [
				"bad",
				{ agent_handle: 123, session_name: "bad", status: "running" },
				{
					agent_handle: "worker-1",
					agent_id_short: "abc123ef",
					agent_type: "worker",
					model: "anthropic/claude-sonnet",
					session_name: "worker",
					status: "running",
					created_at: "2026-01-01T00:00:00Z",
					started_at: "2026-01-01T00:00:01Z",
					ended_at: null,
					recent_activity: [{ kind: "tool_call", snippet: "hidden" }],
					task: {
						goal: "Build the thing",
						task_plan: [{ index: 0, label: "Retired detail", status: "completed" }],
						current_task: { index: 1, label: "Write tests", status: "active" },
					},
				},
			],
		});

		assert.deepEqual(result, {
			agents: [
				{
					agent_handle: "worker-1",
					agent_type: "worker",
					session_name: "worker",
					status: "running",
					created_at: "2026-01-01T00:00:00Z",
					started_at: "2026-01-01T00:00:01Z",
					task: { goal: "Build the thing", current_task: { label: "Write tests" } },
				},
			],
		});
	});

	it("returns null for non-object summary payloads", () => {
		assert.equal(parseRunSummaryResponse(null), null);
		assert.equal(parseRunSummaryResponse("bad"), null);
	});
});
