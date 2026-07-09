import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, it } from "node:test";
import { readRunResultSidecar, resolveRunResultPath, upsertRunResultAttempt } from "../daemon/run-result.ts";

const tempDirs: string[] = [];

async function tempHome(): Promise<string> {
	const directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), "basecamp-run-result-"));
	tempDirs.push(directory);
	return directory;
}

afterEach(async () => {
	await Promise.all(tempDirs.splice(0).map((directory) => fs.promises.rm(directory, { recursive: true, force: true })));
});

describe("daemon run result sidecar", () => {
	it("resolves result.json below the run-owned agent directory", () => {
		const fakeHome = path.join(path.sep, "tmp", "fake-home");
		assert.equal(
			resolveRunResultPath("agent-1", "run-1", fakeHome),
			path.join(fakeHome, ".pi", "basecamp", "swarm", "agents", "agent-1", "runs", "run-1", "result.json"),
		);
	});

	it("uses one result path per run id", () => {
		const fakeHome = path.join(path.sep, "tmp", "fake-home");
		const first = resolveRunResultPath("agent-1", "run-1", fakeHome);
		const second = resolveRunResultPath("agent-1", "run-2", fakeHome);
		assert.notEqual(first, second);
		assert.equal(
			path.dirname(first),
			path.join(fakeHome, ".pi", "basecamp", "swarm", "agents", "agent-1", "runs", "run-1"),
		);
		assert.equal(
			path.dirname(second),
			path.join(fakeHome, ".pi", "basecamp", "swarm", "agents", "agent-1", "runs", "run-2"),
		);
	});

	it("appends and upserts attempts into the sidecar JSON", async () => {
		const home = await tempHome();
		const filePath = resolveRunResultPath("agent-1", "run-1", home);

		await upsertRunResultAttempt(
			filePath,
			{ run_id: "run-1", agent_id: "agent-1" },
			{
				attempt: 1,
				status: "error",
				result: null,
				error: "empty result",
			},
		);
		await upsertRunResultAttempt(
			filePath,
			{ run_id: "run-1", agent_id: "agent-1" },
			{
				attempt: 2,
				status: "ok",
				result: "done",
				error: null,
			},
		);
		await upsertRunResultAttempt(
			filePath,
			{ run_id: "run-1", agent_id: "agent-1" },
			{
				attempt: 1,
				status: "error",
				result: null,
				error: "still empty",
			},
		);

		assert.deepEqual(await readRunResultSidecar(filePath), {
			run_id: "run-1",
			agent_id: "agent-1",
			attempts: [
				{ attempt: 1, status: "error", result: null, error: "still empty" },
				{ attempt: 2, status: "ok", result: "done", error: null },
			],
			final: null,
		});
	});
});
