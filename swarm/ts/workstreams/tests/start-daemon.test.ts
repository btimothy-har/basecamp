import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { resetSessionProductRoleForTesting } from "#core/platform/product-role.ts";
import type { WorkspaceWorktree } from "#core/platform/workspace.ts";
import { startWorkstream, type WorkstreamStartDeps } from "../start.ts";
import { FakeDaemonClient, makeCtx, makeDeps, makeWorkspace, makeWorkstreamDetail } from "./start-harness.ts";

async function runStart(
	pi: ExtensionAPI,
	ctx: ExtensionContext,
	flagValue: string | undefined,
	deps: WorkstreamStartDeps,
) {
	await startWorkstream(pi, ctx, flagValue, deps);
}

describe("workstream startup (daemon-backed)", () => {
	afterEach(resetSessionProductRoleForTesting);

	it("infers the workstream from the copilot/<slug> worktree label and attaches + injects the brief", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /# Herdr workstream launch brief/);
		assert.match(piMessages[0]!, /Launch Workstream Too/);
		assert.match(piMessages[0]!, /attached to the workstream/);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "steady-amber-otter");
		assert.equal(client.attachCalls[0]?.repo, "org/repo");
		assert.equal(client.attachCalls[0]?.worktreeLabel, "copilot/steady-amber-otter");
		assert.equal(client.attachCalls[0]?.status, "attached");
	});

	it("resolves an explicit --workstream=<slug> and attaches", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(makeWorkstreamDetail({ slug: "explicit-slug", id: "ws-explicit" }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, "explicit-slug", harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /# Herdr workstream launch brief/);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "explicit-slug");
	});

	it("resolves an explicit --workstream=<id> and attaches", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(makeWorkstreamDetail({ slug: "id-slug", id: "ws-id-123" }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, "ws-id-123", harness.deps);

		assert.equal(piMessages.length, 1);
		assert.equal(client.attachCalls.length, 1);
		assert.equal(client.attachCalls[0]?.workstream, "ws-id-123");
	});

	it("appends agents — a second attach call adds a second agent entry", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);
		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(client.attachCalls.length, 2, "attach should append, not overwrite");
		assert.equal(client.attachCalls[0]?.workstream, "steady-amber-otter");
		assert.equal(client.attachCalls[1]?.workstream, "steady-amber-otter");
		assert.equal(piMessages.length, 2);
	});

	it("notifies without blocking when attach fails, but still injects the brief", async () => {
		const client = new FakeDaemonClient();
		client.setAttachStatus("error");
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1, "brief should still be injected");
		assert.match(piMessages[0]!, /attach to the daemon failed/);
		assert.match(notices[0]?.message ?? "", /attach/i);
	});

	it("notifies when the workstream is not found on attach but still injects the brief", async () => {
		const client = new FakeDaemonClient();
		client.setAttachStatus("not_found");
		const harness = makeDeps(client);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 1);
		assert.match(piMessages[0]!, /did not find workstream/);
		assert.match(notices[0]?.message ?? "", /not found/i);
	});

	it("reports an error for a bare --workstream without an active worktree", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(makeWorkspace({ activeWorktree: null }));
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not in a worktree/);
	});

	it("reports an error when the worktree label is not a copilot/<slug> worktree and no explicit flag is given", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(
			makeWorkspace({
				activeWorktree: {
					kind: "git-worktree",
					label: "wt-bt/other",
					path: "/w",
					branch: "bt/o",
					created: false,
				} as WorkspaceWorktree,
			}),
		);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not a copilot/);
	});

	it("reports an error when the workstream cannot be resolved from the daemon", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setDetail(null);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /No workstream found/);
	});

	it("fails closed when the repository workspace cannot be determined", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkspace(null);
		harness.setWaitedWorkspace(null);
		const piMessages: string[] = [];
		const fakePi = { sendUserMessage: (t: string) => piMessages.push(t) } as unknown as ExtensionAPI;
		const { ctx, notices } = makeCtx();

		await runStart(fakePi, ctx, undefined, harness.deps);

		assert.equal(piMessages.length, 0);
		assert.equal(client.attachCalls.length, 0);
		assert.match(notices[0]?.message ?? "", /not in a repository workspace/);
	});
});
