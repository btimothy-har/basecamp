import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import { defaultTasksDir, tasksFilePath } from "../tasks/tasks.ts";

describe("tasks path helpers", () => {
	it("builds task paths under the Basecamp tasks directory", () => {
		const homeDir = path.join("tmp", "home");
		const tasksDir = path.join(homeDir, ".pi", "basecamp", "tasks");

		assert.equal(defaultTasksDir(homeDir), tasksDir);
		assert.equal(tasksFilePath("session-1", defaultTasksDir(homeDir)), path.join(tasksDir, "session-1.json"));
	});
});
