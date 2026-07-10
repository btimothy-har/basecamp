import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { executeListWorkstreams, type ListWorkstreamsResultDetails } from "../tools.ts";
import { FakeDaemonClient, makeDeps, makeWorkstreamDetail, makeWorkstreamSummary } from "./tools-harness.ts";

describe("list_workstreams", () => {
	it("lists workstreams from the daemon with filters", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamSummaries([
			makeWorkstreamSummary({ slug: "alpha", label: "Alpha" }),
			makeWorkstreamSummary({ slug: "beta", label: "Beta" }),
		]);

		const result = await executeListWorkstreams({ status: "open" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 2);
		assert.equal(details.workstreams[0]?.slug, "alpha");
		assert.equal(details.workstreams[1]?.slug, "beta");
	});

	it("returns the detail with agents view for a single-identifier query", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const detail = makeWorkstreamDetail({
			slug: "alpha",
			agents: [
				{
					agent_id: "agent-1",
					agent_handle: "quiet-badger-3dc",
					repo: "org/repo",
					worktree_label: "copilot/alpha",
					status: "attached",
					error: null,
					joined_at: "2026-07-03T00:00:00.000Z",
					run_status: "running",
				},
			],
		});
		harness.setWorkstreamDetail("alpha", detail);

		const result = await executeListWorkstreams({ query: "alpha" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 1);
		assert.ok(details.workstream);
		assert.equal(details.workstream.agents.length, 1);
		assert.equal(details.workstream.agents[0]?.agent_handle, "quiet-badger-3dc");
		assert.match(details.next_step, /quiet-badger-3dc/);
	});

	it("falls through to list when single query does not match a detail", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamSummaries([makeWorkstreamSummary({ slug: "alpha" })]);

		const result = await executeListWorkstreams({ query: "nonexistent" }, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(details.status, "ok");
		assert.equal(details.count, 1);
		assert.equal(details.workstream, undefined);
	});

	it("fails when the daemon returns null (not connected)", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client, { listWorkstreamSummaries: async () => null });

		const result = await executeListWorkstreams({}, harness.deps);
		const details = result.details as ListWorkstreamsResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("passes repo, dossierPath, and status filters through", async () => {
		const client = new FakeDaemonClient();
		let capturedFilter: Record<string, unknown> = {};
		const harness = makeDeps(client, {
			listWorkstreamSummaries: async (_sp, filter) => {
				capturedFilter = filter;
				return [];
			},
		});

		await executeListWorkstreams({ repo: "org/repo", dossierPath: "/d.md", status: "closed" }, harness.deps);

		assert.deepEqual(capturedFilter, { repo: "org/repo", dossierPath: "/d.md", status: "closed" });
	});
});
