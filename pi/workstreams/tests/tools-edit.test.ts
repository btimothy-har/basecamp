import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { editParams, FakeDaemonClient, makeDeps, makeWorkstreamDetail, runEdit } from "./tools-harness.ts";

describe("edit_workstream", () => {
	it("revises the brief, bumps the version, and keeps the old version", async () => {
		const client = new FakeDaemonClient({ reviseStatus: "revised", reviseVersion: 2 });
		const harness = makeDeps(client);
		harness.setWorkstreamDetail(
			"steady-amber-otter",
			makeWorkstreamDetail({ id: "ws-1", label: "Alpha", brief: "Old brief", constraints: "keep small" }),
		);

		const { details } = await runEdit(editParams("steady-amber-otter", { brief: "Refined brief" }), harness.deps);

		assert.equal(details.status, "edited");
		assert.equal(details.slug, "steady-amber-otter");
		assert.equal(details.id, "ws-1");
		assert.equal(details.version, 2);
		assert.match(details.message, /version 2/);
		assert.match(details.message, /prior version is retained/i);
		assert.equal(client.reviseCalls.length, 1);
		assert.equal(client.reviseCalls[0]?.workstream, "ws-1");
		assert.equal(client.reviseCalls[0]?.brief, "Refined brief");
	});

	it("carries forward fields that were not provided", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamDetail(
			"steady-amber-otter",
			makeWorkstreamDetail({ label: "Alpha", brief: "Old brief", constraints: "keep small" }),
		);

		await runEdit(editParams("steady-amber-otter", { brief: "Refined brief" }), harness.deps);

		// Only brief changed; label and constraints carry forward from the current version.
		assert.equal(client.reviseCalls[0]?.label, "Alpha");
		assert.equal(client.reviseCalls[0]?.brief, "Refined brief");
		assert.equal(client.reviseCalls[0]?.constraints, "keep small");
	});

	it("requires at least one field to change", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);
		harness.setWorkstreamDetail("steady-amber-otter", makeWorkstreamDetail());

		const { result, details } = await runEdit(editParams("steady-amber-otter"), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /at least one of label, brief, or constraints/);
		assert.equal(client.reviseCalls.length, 0);
	});

	it("returns not_found when the workstream does not resolve", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		const { result, details } = await runEdit(editParams("nonexistent", { brief: "x" }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "not_found");
		assert.match(details.message, /No workstream found/);
		assert.equal(client.reviseCalls.length, 0);
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });
		const { result, details } = await runEdit(editParams("steady-amber-otter", { brief: "x" }), harness.deps);

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /hub is not connected/);
	});
});
