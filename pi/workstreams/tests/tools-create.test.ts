import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { createParams, FakeDaemonClient, makeDeps, runCreate } from "./tools-harness.ts";

describe("create_workstream", () => {
	it("creates a record with a unique slug and does not touch worktree/herdr", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { details } = await runCreate(createParams(), harness.deps);

		assert.equal(details.status, "created");
		assert.equal(details.slug, "steady-amber-otter");
		assert.equal(details.id, client.createCalls[0]?.workstreamId);
		assert.equal(client.createCalls.length, 1);
		assert.equal(client.createCalls[0]?.label, "Launch Workstream Too");
		assert.equal(client.createCalls[0]?.sourceDossierPath, "/graph/pages/Dossier.md");
		assert.equal(client.createCalls[0]?.constraints, "Stay in scope.");
		// Record-only: no worktree provisioning, no Herdr pane.
		assert.equal(harness.provisionCalls.length, 0);
		assert.equal(harness.herdrCalls.length, 0);
		assert.match(details.next_step, /launch_workstream/);
	});

	it("validates non-empty required input at the execution boundary", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { result, details } = await runCreate(createParams({ source: { dossierPath: " " } }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /source\.dossierPath/);
		assert.equal(client.createCalls.length, 0);
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });
		const { result, details } = await runCreate(createParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /hub is not connected/);
	});

	it("regenerates slug on slug_conflict and retries the create", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		let callCount = 0;
		client.createWorkstream = async (input) => {
			callCount += 1;
			client.createCalls.push(input);
			if (callCount === 1) {
				return { status: "slug_conflict", workstream_id: null, slug: null, error: "slug taken" };
			}
			return { status: "created", workstream_id: input.workstreamId, slug: input.slug, error: null };
		};

		const { details } = await runCreate(createParams(), harness.deps);

		assert.equal(details.status, "created");
		assert.equal(details.slug, "calm-cedar-heron");
		assert.ok(callCount >= 2, "should have retried the create");
	});

	it("fails when the daemon rejects creation with an error", async () => {
		const client = new FakeDaemonClient({ createStatus: "error" });
		const harness = makeDeps(client);
		const { result, details } = await runCreate(createParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /Daemon rejected workstream creation/);
	});
});
