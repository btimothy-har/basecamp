import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { buildRunSummaryPath, parseRunSummaryResponse } from "../daemon/client.ts";

describe("daemon run summary client", () => {
	it("encodes root_id and clamps limits in the summary path", () => {
		assert.equal(
			buildRunSummaryPath("root id/with?chars", 500),
			"/runs/summary?root_id=root%20id%2Fwith%3Fchars&limit=50",
		);
		assert.equal(buildRunSummaryPath("root", -12), "/runs/summary?root_id=root&limit=0");
		assert.equal(buildRunSummaryPath("root", 4.8), "/runs/summary?root_id=root&limit=4");
	});

	it("parses valid agent task detail and ignores malformed rows", () => {
		const result = parseRunSummaryResponse({
			root_id: "root",
			session_active: true,
			agents: [
				"bad",
				{ agent_handle: 123, session_name: "bad", status: "running" },
				{
					agent_handle: "worker-1",
					agent_type: "worker",
					session_name: "worker",
					status: "running",
					created_at: "2026-01-01T00:00:00Z",
					started_at: "2026-01-01T00:00:01Z",
					ended_at: null,
					task: {
						goal: "Build the thing",
						task_plan: [
							{ index: 0, label: "Done", status: "completed" },
							"bad",
							{ index: 1, label: "Now", status: "active" },
						],
						current_task: { index: 1, label: "Now", status: "active", notes: "ignored" },
					},
					latest_message: "not part of the TS summary surface",
				},
			],
		});

		assert.ok(result);
		assert.equal(result.root_id, "root");
		assert.equal(result.session_active, true);
		assert.equal(result.agents.length, 1);
		const [agent] = result.agents;
		assert.equal(agent?.agent_handle, "worker-1");
		assert.equal(agent?.task?.goal, "Build the thing");
		assert.deepEqual(
			agent?.task?.task_plan?.map((item) => item.label),
			["Done", "Now"],
		);
		assert.deepEqual(agent?.task?.current_task, { index: 1, label: "Now", status: "active" });
		assert.equal(Object.hasOwn(agent ?? {}, "latest_message"), false);
	});

	it("returns null for non-object summary payloads", () => {
		assert.equal(parseRunSummaryResponse(null), null);
		assert.equal(parseRunSummaryResponse("bad"), null);
	});
});
