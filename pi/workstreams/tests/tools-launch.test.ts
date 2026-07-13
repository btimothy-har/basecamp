import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { WorkspaceWorktree } from "#core/project/workspace/state.ts";
import {
	FakeDaemonClient,
	launchParams,
	makeDeps,
	makeWorkspace,
	makeWorkstreamDetail,
	runLaunch,
} from "./tools-harness.ts";

function seedWorkstream(harness: ReturnType<typeof makeDeps>, slug: string, overrides = {}) {
	harness.setWorkstreamDetail(slug, makeWorkstreamDetail({ slug, ...overrides }));
}

describe("launch_workstream validation", () => {
	it("validates a non-empty workstream identifier", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		const { result, details } = await runLaunch(launchParams(" "), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /non-empty workstream/);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("fails when no repo workspace is available", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "steady-amber-otter");
		harness.setWorkspace(makeWorkspace({ repo: null }));
		const { result, details } = await runLaunch(launchParams(), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /current git repository/);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("fails with a create hint when the workstream does not resolve", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		const { result, details } = await runLaunch(launchParams("nonexistent"), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /No workstream found/);
		assert.match(details.next_step, /create_workstream/);
		assert.equal(harness.provisionCalls.length, 0);
	});
});

describe("launch_workstream provisioning", () => {
	it("provisions the copilot/<slug> worktree and opens a Herdr pane for an existing workstream", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		seedWorkstream(harness, "steady-amber-otter", { id: "ws-1", label: "Alpha" });

		const { details } = await runLaunch(launchParams("steady-amber-otter"), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.slug, "steady-amber-otter");
		assert.equal(details.id, "ws-1");
		assert.equal(harness.provisionCalls.length, 1);
		assert.equal(harness.provisionCalls[0]?.label, "copilot/steady-amber-otter");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/alpha");
		assert.equal(details.worktree?.label, "copilot/steady-amber-otter");
		assert.match(details.next_step, /pi --workstream/);
		// launch never creates or edits the workstream record.
		assert.equal(client.createCalls.length, 0);
		assert.equal(client.reviseCalls.length, 0);
	});

	it("uses worktreeSlug for the bt/ branch name", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "steady-amber-otter", { label: "Ignored Label" });

		const { details } = await runLaunch(
			launchParams("steady-amber-otter", { worktreeSlug: "feature-launch" }),
			harness.deps,
		);

		assert.equal(details.status, "launched");
		assert.equal(harness.provisionCalls[0]?.branchName, "bt/feature-launch");
		assert.equal(details.worktree?.branch, "bt/feature-launch");
	});

	it("fails when the derived branch is already checked out", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "steady-amber-otter", { label: "Alpha" });
		harness.setListedWorktrees([
			{
				kind: "git-worktree",
				label: "other-wt",
				path: "/worktrees/existing",
				branch: "bt/alpha",
				created: false,
			} as WorkspaceWorktree,
		]);

		const { result, details } = await runLaunch(launchParams("steady-amber-otter"), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /branch bt\/alpha is already checked out/);
		assert.equal(harness.provisionCalls.length, 0);
	});

	it("reuses the workstream's own worktree on relaunch instead of tripping the branch guard", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "steady-amber-otter", { label: "Alpha" });
		// The workstream's own copilot/<slug> worktree already holds the derived branch.
		harness.setListedWorktrees([
			{
				kind: "git-worktree",
				label: "copilot/steady-amber-otter",
				path: "/worktrees/org/repo/copilot/steady-amber-otter",
				branch: "bt/alpha",
				created: false,
			} as WorkspaceWorktree,
		]);

		const { result, details } = await runLaunch(launchParams("steady-amber-otter"), harness.deps);

		assert.equal(result.isError ?? false, false);
		assert.equal(details.status, "launched");
		assert.equal(harness.provisionCalls.length, 1);
	});

	it("fails when worktree provisioning throws", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "steady-amber-otter");
		harness.setProvision(async () => {
			throw new Error("cannot create branch");
		});

		const { result, details } = await runLaunch(launchParams("steady-amber-otter"), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /cannot create branch/);
	});

	it("returns transient setup and herdr summaries inline, not persisted", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		seedWorkstream(harness, "steady-amber-otter");
		harness.setSetupCommand("make setup");

		const { details } = await runLaunch(launchParams("steady-amber-otter"), harness.deps);

		assert.equal(details.status, "launched");
		assert.ok(details.setup_summary);
		assert.ok(details.herdr_summary);
		assert.equal(harness.setupCalls.length, 1);
		assert.equal(harness.herdrCalls.length, 1);
		assert.equal(client.attachCalls.length, 0);
		assert.equal(client.updateCalls.length, 0);
	});

	it("provisions the worktree idempotently (reuses if present)", async () => {
		const harness = makeDeps(new FakeDaemonClient());
		seedWorkstream(harness, "carry-slug", { id: "ws-carry" });
		harness.setCreated(false);

		const { details } = await runLaunch(launchParams("carry-slug"), harness.deps);

		assert.equal(details.status, "launched");
		assert.equal(details.worktree?.created, false);
	});
});
