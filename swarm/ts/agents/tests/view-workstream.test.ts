import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
	buildWorkstreamsPath,
	parseWorkstreamDetailResponse,
	parseWorkstreamsResponse,
} from "../daemon/view/workstream.ts";

describe("daemon workstream HTTP helpers", () => {
	it("buildWorkstreamsPath builds the correct path with only provided filters", () => {
		assert.equal(buildWorkstreamsPath({}), "/workstreams");
		assert.equal(buildWorkstreamsPath({ status: "open" }), "/workstreams?status=open");
		assert.equal(
			buildWorkstreamsPath({ status: "closed", repo: "org/repo" }),
			"/workstreams?status=closed&repo=org%2Frepo",
		);
		assert.equal(
			buildWorkstreamsPath({ dossierPath: "/tmp/d.md", query: "alp" }),
			"/workstreams?dossier_path=%2Ftmp%2Fd.md&query=alp",
		);
	});

	it("parseWorkstreamsResponse parses a sample {workstreams:[...]} payload", () => {
		const result = parseWorkstreamsResponse({
			workstreams: [
				{
					id: "ws-1",
					slug: "alpha",
					label: "Alpha",
					brief: "Do the thing",
					constraints: null,
					source_dossier_path: "/tmp/dossier.md",
					source_repo_page_path: null,
					status: "open",
					created_at: "2026-01-01T00:00:00Z",
					updated_at: "2026-01-01T00:00:01Z",
					agent_count: 2,
				},
				"bad",
			],
		});

		assert.ok(result);
		assert.equal(result.length, 1);
		const [ws] = result;
		assert.equal(ws?.id, "ws-1");
		assert.equal(ws?.slug, "alpha");
		assert.equal(ws?.agent_count, 2);
	});

	it("parseWorkstreamsResponse returns null for non-object payloads", () => {
		assert.equal(parseWorkstreamsResponse(null), null);
		assert.equal(parseWorkstreamsResponse("bad"), null);
	});

	it("parseWorkstreamDetailResponse parses a sample detail payload with agents", () => {
		const result = parseWorkstreamDetailResponse({
			id: "ws-1",
			slug: "alpha",
			label: "Alpha",
			brief: "Do the thing",
			constraints: "stay small",
			source_dossier_path: "/tmp/dossier.md",
			source_repo_page_path: "/tmp/page.md",
			status: "open",
			created_at: "2026-01-01T00:00:00Z",
			updated_at: "2026-01-01T00:00:01Z",
			agent_count: 1,
			agents: [
				{
					agent_id: "agent-1",
					agent_handle: "quiet-badger-3dc450",
					repo: "org/repo",
					worktree_label: "wt-1",
					status: "attached",
					error: null,
					joined_at: "2026-01-01T00:00:02Z",
					run_status: "running",
				},
				"bad",
			],
		});

		assert.ok(result);
		assert.equal(result.id, "ws-1");
		assert.equal(result.agents.length, 1);
		const [agent] = result.agents;
		assert.equal(agent?.agent_handle, "quiet-badger-3dc450");
		assert.equal(agent?.run_status, "running");
	});

	it("parseWorkstreamDetailResponse returns null for non-object payloads", () => {
		assert.equal(parseWorkstreamDetailResponse(null), null);
		assert.equal(parseWorkstreamDetailResponse("bad"), null);
	});

	it("listWorkstreams returns null when the underlying request yields null", () => {
		assert.equal(parseWorkstreamsResponse(null), null);
	});
});
