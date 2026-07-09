import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { executeSetWorkstreamStatus, type SetWorkstreamStatusResultDetails } from "../tools.ts";
import { FakeDaemonClient, makeDeps } from "./tools-harness.ts";

describe("set_workstream_status", () => {
	it("updates status to open", async () => {
		const client = new FakeDaemonClient({ updateStatus: "updated" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(details.status, "updated");
		assert.match(details.message, /now open/);
		assert.equal(client.updateCalls.length, 1);
		assert.equal(client.updateCalls[0]?.workstream, "alpha");
		assert.equal(client.updateCalls[0]?.status, "open");
	});

	it("updates status to closed", async () => {
		const client = new FakeDaemonClient({ updateStatus: "updated" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "beta", status: "closed" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(details.status, "updated");
		assert.match(details.message, /now closed/);
		assert.equal(client.updateCalls[0]?.status, "closed");
	});

	it("returns not_found when the workstream does not exist", async () => {
		const client = new FakeDaemonClient({ updateStatus: "not_found" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "nope", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "not_found");
		assert.match(details.message, /No workstream found/);
	});

	it("returns invalid_status for an invalid status", async () => {
		const client = new FakeDaemonClient({ updateStatus: "invalid_status" });
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "invalid_status");
	});

	it("fails when no daemon client is available", async () => {
		const harness = makeDeps(new FakeDaemonClient(), { getClient: async () => null });

		const result = await executeSetWorkstreamStatus({ workstream: "alpha", status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /daemon is not connected/);
	});

	it("validates required params", async () => {
		const client = new FakeDaemonClient();
		const harness = makeDeps(client);

		const result = await executeSetWorkstreamStatus({ status: "open" }, harness.deps);
		const details = result.details as SetWorkstreamStatusResultDetails;

		assert.equal(result.isError, true);
		assert.equal(details.status, "failed");
		assert.match(details.message, /requires a non-empty workstream/);
		assert.equal(client.updateCalls.length, 0);
	});
});
