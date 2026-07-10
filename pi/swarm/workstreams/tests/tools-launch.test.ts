import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "#core/workspace/service.ts";
import {
	baseParams,
	FakeDaemonClient,
	makeDeps,
	makeWorkspace,
	makeWorkstreamDetail,
	runLaunch,
} from "./tools-harness.ts";

describe("launch_workstream validation", () => {
	it("validates non-empty required input at the execution boundary", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { result, details } = await runLaunch(baseParams({ source: { dossierPath: " " } }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /source\.dossierPath/);
		assert.equal(client.createCalls.length, 0);
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });
		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("fails when no repo workspace is available", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(makeWorkspace({ repo: null }));
		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /current git repository/);
		assert.equal(client.createCalls.length, 0);
	});
});

describe("launch_workstream CREATE path", () => {
	it("creates a workstream with a unique slug and provisions the worktree", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "steady-amber-otter");
		assert.equal(harness.provisionCalls.length, 1);
		assert.equal(harness.provisionCalls[0]?.label, "copilot/steady-amber-otter");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/launch-workstream-too");
		assert.equal(details.worktree?.label, "copilot/steady-amber-otter");
		assert.match(details.next_step, /pi --workstream=/);
		assert.equal(client.createCalls.length, 1);
		assert.equal(client.createCalls[0]?.slug, "steady-amber-otter");
		assert.equal(client.createCalls[0]?.label, "Launch Workstream Too");
		assert.equal(client.createCalls[0]?.sourceDossierPath, "/graph/pages/Dossier.md");
	});

	it("regenerates slug on slug_conflict and retries the create", async () => {
		const client = new FakeDaemonClient({ createStatus: "slug_conflict" });
		const harness = makeDeps(client);

		// First call returns slug_conflict, then we flip to created on retry
		let callCount = 0;
		const originalCreate = client.createWorkstream.bind(client);
		client.createWorkstream = async (input) => {
			callCount += 1;
			if (callCount === 1) {
				client.createCalls.push(input);
				return { status: "slug_conflict", workstream_id: null, slug: null, error: "slug taken" };
			}
			return originalCreate(input);
		};
		client.setOpts({ createStatus: "created" });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "calm-cedar-heron");
		assert.ok(callCount >= 2, "should have retried create");
	});

	it("regenerates slug when the generated slug already exists in the daemon", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamDetail("steady-amber-otter", makeWorkstreamDetail());

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "calm-cedar-heron");
		assert.equal(client.createCalls[0]?.slug, "calm-cedar-heron");
	});

	it("fails when the derived branch is already checked out", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setListedWorktrees([
			{
				kind: "git-worktree",
				label: "other-wt",
				path: "/worktrees/existing",
				branch: "bt/launch-workstream-too",
				created: false,
			} as WorkspaceWorktree,
		]);

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /branch bt\/launch-workstream-too is already checked out/);
		assert.equal(client.createCalls.length, 0);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("fails when worktree provisioning throws", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setProvision(async () => {
			throw new Error("cannot create branch");
		});

		const { result, details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /cannot create branch/);
		assert.equal(client.createCalls.length, 0);
	});

	it("returns transient setup and herdr summaries inline, not persisted", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setSetupCommand("make setup");
		harness.setHerdrResult({ status: "opened", message: "opened", args: [] });

		const { details } = await runLaunch(baseParams(), harness.deps);

		assert.equal(details.status, "launched");
		assert.ok(details.setup_summary);
		assert.ok(details.herdr_summary);
		assert.equal(harness.setupCalls.length, 1);
		assert.equal(harness.herdrCalls.length, 1);
		// No persistence calls beyond createWorkstream
		assert.equal(client.attachCalls.length, 0);
		assert.equal(client.updateCalls.length, 0);
	});

	it("uses worktreeSlug for the bt/ branch name", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const { details } = await runLaunch(
			baseParams({ workstream: { label: "Ignored Label", brief: "Brief.", worktreeSlug: "feature-launch" } }),
			harness.deps,
		);

		assert.equal(details.status, "launched");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/feature-launch");
		assert.equal(details.worktree?.branch, "bt/feature-launch");
	});
});

describe("launch_workstream CARRY path", () => {
	it("resolves an existing workstream and reuses the worktree without creating a new workstream", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const existing = makeWorkstreamDetail({ slug: "existing-slug", id: "ws-existing", label: "Existing" });
		harness.setWorkstreamDetail("existing-slug", existing);

		const { details } = await runLaunch(baseParams({ workstream_id: "existing-slug" }), harness.deps);

		assert.equal(details.status, "carried");
		assert.equal(details.slug, "existing-slug");
		assert.equal(details.id, "ws-existing");
		assert.equal(harness.provisionCalls.length, 1);
		assert.equal(harness.provisionCalls[0]?.label, "copilot/existing-slug");
		assert.equal(client.createCalls.length, 0, "should not call createWorkstream on carry");
	});

	it("fails when the carry identifier does not resolve", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		const { result, details } = await runLaunch(baseParams({ workstream_id: "nonexistent" }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /No workstream found/);
		assert.equal(client.createCalls.length, 0);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("provisions the worktree idempotently (reuses if present)", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const existing = makeWorkstreamDetail({ slug: "carry-slug", id: "ws-carry" });
		harness.setWorkstreamDetail("carry-slug", existing);
		harness.setCreated(false);

		const { details } = await runLaunch(baseParams({ workstream_id: "carry-slug" }), harness.deps);

		assert.equal(details.status, "carried");
		assert.equal(details.worktree?.created, false);
	});
});
