import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";
import type { GoalCycle } from "../../schemas/task.ts";
import { loadCycles, saveCycles, TASKS_SCHEMA_VERSION } from "../store.ts";

function tmpFile(): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "basecamp-tasks-store-"));
	return path.join(dir, "session.json");
}

function cycle(goal: string): GoalCycle {
	return {
		goal,
		tasks: [{ label: "T1", description: "d", criteria: "c", status: "active", review: null }],
		planRef: null,
		active: true,
		archivedAt: null,
	};
}

describe("tasks/store versioned persistence", () => {
	it("writes a { version, cycles } envelope and round-trips", () => {
		const file = tmpFile();
		saveCycles(file, [cycle("Ship it")]);

		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		assert.equal(raw.version, TASKS_SCHEMA_VERSION);
		assert.equal(raw.cycles.length, 1);

		const loaded = loadCycles(file);
		assert.equal(loaded.length, 1);
		assert.equal(loaded[0]!.goal, "Ship it");
	});

	it("migrates a legacy bare-array file and strips residual notes", () => {
		const file = tmpFile();
		fs.writeFileSync(
			file,
			JSON.stringify([
				{
					goal: "Legacy",
					active: true,
					archivedAt: null,
					planRef: null,
					tasks: [{ label: "T1", description: "d", criteria: "c", status: "active", review: null, notes: "stale" }],
				},
			]),
		);

		const loaded = loadCycles(file);
		assert.equal(loaded.length, 1);
		assert.equal(loaded[0]!.goal, "Legacy");
		assert.ok(!("notes" in loaded[0]!.tasks[0]!));

		saveCycles(file, loaded);
		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		assert.equal(raw.version, TASKS_SCHEMA_VERSION);
		assert.ok(!("notes" in raw.cycles[0].tasks[0]));
	});

	it("returns [] for missing, malformed, or cycle-less files", () => {
		assert.deepEqual(loadCycles(path.join(os.tmpdir(), "basecamp-missing-xyz.json")), []);

		const file = tmpFile();
		fs.writeFileSync(file, "not json");
		assert.deepEqual(loadCycles(file), []);

		fs.writeFileSync(file, JSON.stringify({ version: 1 }));
		assert.deepEqual(loadCycles(file), []);
	});
});
